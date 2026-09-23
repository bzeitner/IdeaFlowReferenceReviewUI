from django import forms


STATUS_CHOICES = [
    ("", "Choose a judgment"),
    ("pass", "Pass"),
    ("fail", "Fail"),
    ("not_applicable", "Not applicable"),
    ("insufficient_evidence", "Insufficient evidence"),
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
        evidence_choices = [
            (key, f"{key} · {value['kind']}") for key, value in self.evidence.items()
        ]
        for index, criterion in enumerate(self.criteria):
            self.fields[f"status_{index}"] = forms.ChoiceField(
                choices=STATUS_CHOICES,
                label="Judgment",
            )
            self.fields[f"reason_{index}"] = forms.CharField(
                max_length=1500,
                label="Reason",
                widget=forms.Textarea(attrs={"rows": 3}),
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
            status = cleaned.get(f"status_{index}")
            refs = cleaned.get(f"refs_{index}") or []
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
        return {
            "criterion_results": [
                {
                    "id": criterion["id"],
                    "status": self.cleaned_data[f"status_{index}"],
                    "reason": self.cleaned_data[f"reason_{index}"].strip(),
                    "evidence_refs": self.cleaned_data.get(f"refs_{index}") or [],
                }
                for index, criterion in enumerate(self.criteria)
            ],
            "progress_score": self.cleaned_data.get("progress_score")
            if "anchors" in self.packet["rubric"]
            else None,
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
