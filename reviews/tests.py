import io
import json
import tarfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import ReviewBundle


def packet(case_id=2, plan_hash="a" * 64, assisted=False):
    criterion = {
        "id": "evidence.support",
        "dimension": "evidence_references",
        "description": "Claims have support.",
        "method": "human",
        "severity": "ordinary",
        "required_inputs": ["output", "source_evidence"],
        "applicability": "Applies to this output.",
        "pass_example": "Supported.",
        "fail_example": "Unsupported.",
    }
    value = {
        "plan_hash": plan_hash,
        "case_id": case_id,
        "case_hash": f"{case_id:064x}",
        "rubric_hash": "b" * 64,
        "rubric": {"schema_version": 1, "calibration": "not_calibrated", "criteria": [criterion]},
        "evidence": {
            "output": {"kind": "output", "value": "A supported claim."},
            "source-1": {"kind": "source_evidence", "value": "Supporting passage."},
        },
        "response_schema": {"criterion_results": "rows", "progress_score": "null"},
        "notice": "Review independently.",
    }
    if assisted:
        value.update(
            {
                "review_mode": "model_assisted_error_audit_v1",
                "automated_result": {"id": 42, "hash": "d" * 64},
                "automated_assessment": {
                    "criterion_results": [
                        {
                            "id": "evidence.support",
                            "status": "pass",
                            "reason": "The source supports the claim.",
                            "evidence_refs": ["output", "source-1"],
                        }
                    ],
                    "progress_score": None,
                },
            }
        )
    return value


def archive(*packets, symlink=False):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as bundle:
        if symlink:
            info = tarfile.TarInfo("case.json")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            bundle.addfile(info)
        else:
            for item in packets:
                data = json.dumps(item).encode()
                info = tarfile.TarInfo(f"packets/case-{item['case_id']}.json")
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
    return raw.getvalue()


class ReviewFlowTests(TestCase):
    def upload(self, content=None):
        return self.client.post(
            reverse("upload-bundle"),
            {"display_name": "Reviewer one", "archive": SimpleUploadedFile("packets.tar.gz", content or archive(packet(), packet(3)))},
        )

    def test_import_review_and_export(self):
        response = self.upload()
        self.assertEqual(response.status_code, 302)
        bundle = ReviewBundle.objects.get()
        case = bundle.cases.first()
        response = self.client.post(
            reverse("review-case", args=[bundle.pk, case.case_id]),
            {
                "status_0": "pass",
                "reason_0": "The source supports the output.",
                "refs_0": ["output", "source-1"],
            },
        )
        self.assertEqual(response.status_code, 302)
        case.refresh_from_db()
        self.assertTrue(case.completed)
        second = bundle.cases.last()
        self.client.post(
            reverse("review-case", args=[bundle.pk, second.case_id]),
            {"status_0": "insufficient_evidence", "reason_0": "Cannot verify.", "refs_0": []},
        )
        response = self.client.get(reverse("export-bundle", args=[bundle.pk]))
        body = b"".join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(body)) as exported:
            assessment = json.loads(exported.read("case-2-assessment.json"))
        self.assertEqual(assessment["criterion_results"][0]["status"], "pass")
        self.assertIsNone(assessment["progress_score"])

    def test_pass_requires_all_evidence_kinds(self):
        self.upload()
        bundle = ReviewBundle.objects.get()
        case = bundle.cases.first()
        response = self.client.post(
            reverse("review-case", args=[bundle.pk, case.case_id]),
            {"status_0": "pass", "reason_0": "Looks good.", "refs_0": ["output"]},
        )
        self.assertContains(response, "missing required evidence kinds", status_code=200)
        case.refresh_from_db()
        self.assertFalse(case.completed)

    def test_rejects_mixed_plans_and_archive_links(self):
        mixed = self.upload(archive(packet(), packet(3, plan_hash="c" * 64)))
        self.assertEqual(mixed.status_code, 400)
        self.assertContains(mixed, "one plan", status_code=400)
        linked = self.upload(archive(symlink=True))
        self.assertEqual(linked.status_code, 400)
        self.assertContains(linked, "unsupported member type", status_code=400)

    def test_assisted_review_marks_correct_and_exports_difference_audit(self):
        response = self.upload(archive(packet(2, assisted=True)))
        self.assertEqual(response.status_code, 302)
        bundle = ReviewBundle.objects.get()
        self.assertEqual(bundle.review_mode, "model_assisted_error_audit_v1")
        case = bundle.cases.get()
        response = self.client.post(
            reverse("review-case", args=[bundle.pk, case.case_id]),
            {
                "disposition_0": "correct",
                "status_0": "pass",
                "reason_0": "The source supports the claim.",
                "refs_0": ["output", "source-1"],
            },
        )
        self.assertEqual(response.status_code, 302)
        case.refresh_from_db()
        self.assertTrue(case.comparison["criteria"][0]["automated_grader_correct"])
        response = self.client.get(reverse("export-bundle", args=[bundle.pk]))
        body = b"".join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(body)) as exported:
            audit = json.loads(exported.read("assisted-review-audit.json"))
            envelope = json.loads(exported.read("case-2-assessment.json"))
        self.assertEqual(audit["review_mode"], "model_assisted_error_audit_v1")
        self.assertTrue(audit["cases"][0]["criteria"][0]["automated_grader_correct"])
        self.assertEqual(envelope["automated_result"], packet(2, assisted=True)["automated_result"])
        self.assertEqual(envelope["assessment"], packet(2, assisted=True)["automated_assessment"])
        self.assertTrue(envelope["difference_manifest"]["criteria"][0]["automated_grader_correct"])

    def test_assisted_wrong_requires_an_actual_correction(self):
        self.upload(archive(packet(2, assisted=True)))
        bundle = ReviewBundle.objects.get()
        case = bundle.cases.get()
        response = self.client.post(
            reverse("review-case", args=[bundle.pk, case.case_id]),
            {
                "disposition_0": "wrong",
                "status_0": "pass",
                "reason_0": "The source supports the claim.",
                "refs_0": ["output", "source-1"],
            },
        )
        self.assertContains(response, "Mark correct, or change", status_code=200)
        case.refresh_from_db()
        self.assertFalse(case.completed)

    def test_delete_requires_post(self):
        self.upload()
        bundle = ReviewBundle.objects.get()
        self.assertEqual(self.client.get(reverse("delete-bundle", args=[bundle.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("delete-bundle", args=[bundle.pk])).status_code, 302)
        self.assertFalse(ReviewBundle.objects.exists())
