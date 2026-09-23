import io
import json
import tarfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import ReviewBundle


def packet(case_id=2, plan_hash="a" * 64):
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
    return {
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

    def test_delete_requires_post(self):
        self.upload()
        bundle = ReviewBundle.objects.get()
        self.assertEqual(self.client.get(reverse("delete-bundle", args=[bundle.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("delete-bundle", args=[bundle.pk])).status_code, 302)
        self.assertFalse(ReviewBundle.objects.exists())
