from django import forms


STATUS_CHOICES = [
    ("", "Choose a judgment"),
    ("pass", "Pass"),
    ("fail", "Fail"),
    ("not_applicable", "Not applicable"),
    ("insufficient_evidence", "Insufficient evidence"),
]
DISPOSITION_CHOICES = [
    ("", "Choose one"),
    ("correct", "The automated judgment is correct"),
    ("wrong", "The automated judgment is wrong"),
]


class BundleUploadForm(forms.Form):
    display_name = forms.CharField(
        max_length=120,
        help_text="A local label such as ‘Brad — plan 1’. It is not included in exports.",
    )
    archive = forms.FileField(help_text="The assigned .tar.gz packet archive (maximum 10 MiB).")

    def clean_archive(self):
        archive = self.cleaned_data["archive"]
        if archive.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The archive exceeds the 10 MiB limit.")
        if not archive.name.endswith((".tar.gz", ".tgz")):
            raise forms.ValidationError("Upload the assigned .tar.gz packet archive.")
        return archive


class AssessmentForm(forms.Form):
    def __init__(self, packet, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.packet = packet
        self.criteria = packet["rubric"]["criteria"]
        self.evidence = packet["evidence"]
        self.automated = packet.get("automated_assessment")
        self.automated_by_id = {
            row["id"]: row for row in self.automated.get("criterion_results", [])
        } if self.automated else {}
        evidence_choices = [
            (key, f"{key} · {value['kind']}") for key, value in self.evidence.items()
        ]
        for index, criterion in enumerate(self.criteria):
            if self.automated:
                self.fields[f"disposition_{index}"] = forms.ChoiceField(
                    choices=DISPOSITION_CHOICES,
                    label="Is the automated judgment correct?",
                )
            self.fields[f"status_{index}"] = forms.ChoiceField(
                choices=STATUS_CHOICES,
                label="Judgment",
                required=not self.automated,
            )
            self.fields[f"reason_{index}"] = forms.CharField(
                max_length=1500,
                label="Reason",
                widget=forms.Textarea(attrs={"rows": 3}),
                required=not self.automated,
            )
            self.fields[f"refs_{index}"] = forms.MultipleChoiceField(
                choices=evidence_choices,
                required=False,
                label="Supporting packet references",
                widget=forms.CheckboxSelectMultiple,
            )
        if "anchors" in packet["rubric"]:
            self.fields["progress_score"] = forms.TypedChoiceField(
                choices=[("", "Not judgeable")] + [(str(value), str(value)) for value in range(1, 6)],
                coerce=lambda value: int(value) if value else None,
                required=False,
            )

    def clean(self):
        cleaned = super().clean()
        for index, criterion in enumerate(self.criteria):
            disposition = cleaned.get(f"disposition_{index}") if self.automated else "wrong"
            if self.automated and disposition == "correct":
                continue
            status = cleaned.get(f"status_{index}")
            refs = cleaned.get(f"refs_{index}") or []
            reason = cleaned.get(f"reason_{index}")
            if self.automated and disposition == "wrong":
                if not status:
                    self.add_error(f"status_{index}", "Provide the corrected judgment.")
                if not reason or not reason.strip():
                    self.add_error(f"reason_{index}", "Explain why the automated judgment is wrong.")
            if status in {"pass", "fail"}:
                kinds = {self.evidence[ref]["kind"] for ref in refs}
                required = set(criterion.get("required_inputs", []))
                missing = sorted(required - kinds)
                if not refs:
                    self.add_error(f"refs_{index}", "A pass or fail must cite packet evidence.")
                elif missing:
                    self.add_error(
                        f"refs_{index}",
                        "A pass or fail is missing required evidence kinds: " + ", ".join(missing),
                    )
            if self.automated and disposition == "wrong" and status and reason:
                automated = self.automated_by_id[criterion["id"]]
                corrected = {
                    "id": criterion["id"],
                    "status": status,
                    "reason": reason.strip(),
                    "evidence_refs": refs,
                }
                if corrected == automated:
                    self.add_error(f"reason_{index}", "Mark correct, or change the automated judgment before marking it wrong.")
        if "anchors" in self.packet["rubric"]:
            required_rows = [
                cleaned.get(f"status_{index}")
                for index, criterion in enumerate(self.criteria)
                if criterion.get("severity") != "optional"
            ]
            judgeable = all(status in {"pass", "fail"} for status in required_rows)
            score = cleaned.get("progress_score")
            if judgeable and score is None:
                self.add_error("progress_score", "A judgeable progress assessment requires a 1–5 score.")
            if not judgeable and score is not None:
                self.add_error("progress_score", "Leave the score blank when required judgments are incomplete.")
        return cleaned

    def assessment(self):
        def result(index, criterion):
            if self.automated and self.cleaned_data[f"disposition_{index}"] == "correct":
                return self.automated_by_id[criterion["id"]]
            return {
                "id": criterion["id"],
                "status": self.cleaned_data[f"status_{index}"],
                "reason": self.cleaned_data[f"reason_{index}"].strip(),
                "evidence_refs": self.cleaned_data.get(f"refs_{index}") or [],
            }
        return {
            "criterion_results": [
                result(index, criterion)
                for index, criterion in enumerate(self.criteria)
            ],
            "progress_score": self.cleaned_data.get("progress_score")
            if "anchors" in self.packet["rubric"]
            else None,
        }

    def comparison(self):
        if not self.automated:
            return {}
        final = {row["id"]: row for row in self.assessment()["criterion_results"]}
        return {
            "review_mode": "model_assisted_error_audit_v1",
            "criteria": [
                {
                    "id": criterion["id"],
                    "automated_grader_correct": self.cleaned_data[f"disposition_{index}"] == "correct",
                    "automated": self.automated_by_id[criterion["id"]],
                    "reviewer_final": final[criterion["id"]],
                }
                for index, criterion in enumerate(self.criteria)
            ],
        }

    @classmethod
    def initial_from_assessment(cls, assessment):
        initial = {}
        for index, row in enumerate(assessment.get("criterion_results", [])):
            initial[f"status_{index}"] = row.get("status")
            initial[f"reason_{index}"] = row.get("reason")
            initial[f"refs_{index}"] = row.get("evidence_refs", [])
        initial["progress_score"] = assessment.get("progress_score")
        return initial

    @classmethod
    def initial_for_packet(cls, packet, assessment=None, comparison=None):
        initial = cls.initial_from_assessment(assessment or packet.get("automated_assessment", {}))
        if packet.get("automated_assessment"):
            decisions = {
                row["id"]: row["automated_grader_correct"]
                for row in (comparison or {}).get("criteria", [])
            }
            for index, criterion in enumerate(packet["rubric"]["criteria"]):
                if criterion["id"] in decisions:
                    initial[f"disposition_{index}"] = "correct" if decisions[criterion["id"]] else "wrong"
        return initial
