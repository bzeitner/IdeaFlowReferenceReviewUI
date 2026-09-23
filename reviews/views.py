import io
import json
import zipfile

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import AssessmentForm, BundleUploadForm
from .models import ReviewBundle, ReviewCase
from .packets import read_packet_archive


def home(request):
    return render(request, "reviews/home.html", {"bundles": ReviewBundle.objects.all()})


@transaction.atomic
def upload_bundle(request):
    if request.method != "POST":
        return redirect("home")
    form = BundleUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "reviews/home.html", {"bundles": ReviewBundle.objects.all(), "form": form}, status=400)
    try:
        packets = read_packet_archive(form.cleaned_data["archive"])
    except ValidationError as exc:
        form.add_error("archive", exc.messages[0])
        return render(request, "reviews/home.html", {"bundles": ReviewBundle.objects.all(), "form": form}, status=400)
    first = packets[0]
    bundle = ReviewBundle.objects.create(
        display_name=form.cleaned_data["display_name"],
        source_name=form.cleaned_data["archive"].name,
        plan_hash=first["plan_hash"],
        rubric_hash=first["rubric_hash"],
        review_mode=first.get("review_mode", "independent_blinded_v1"),
    )
    ReviewCase.objects.bulk_create(
        [
            ReviewCase(
                bundle=bundle,
                case_id=packet["case_id"],
                case_hash=packet["case_hash"],
                position=position,
                packet=packet,
            )
            for position, packet in enumerate(packets, start=1)
        ]
    )
    description = "model-assisted audit" if bundle.review_mode == "model_assisted_error_audit_v1" else "blinded review"
    messages.success(request, f"Imported {len(packets)} {description} case packets.")
    return redirect("bundle", bundle_id=bundle.pk)


def bundle_detail(request, bundle_id):
    bundle = get_object_or_404(ReviewBundle, pk=bundle_id)
    cases = list(bundle.cases.all())
    next_case = next((case for case in cases if not case.completed), cases[0] if cases else None)
    return render(request, "reviews/bundle.html", {"bundle": bundle, "cases": cases, "next_case": next_case})


def review_case(request, bundle_id, case_id):
    case = get_object_or_404(ReviewCase, bundle_id=bundle_id, case_id=case_id)
    siblings = list(case.bundle.cases.all())
    index = next(index for index, item in enumerate(siblings) if item.pk == case.pk)
    previous_case = siblings[index - 1] if index else None
    next_case = siblings[index + 1] if index + 1 < len(siblings) else None
    if request.method == "POST":
        form = AssessmentForm(case.packet, request.POST)
        if form.is_valid():
            case.assessment = form.assessment()
            case.comparison = form.comparison()
            case.completed = True
            case.save(update_fields=["assessment", "comparison", "completed", "updated_at"])
            messages.success(request, f"Saved case {case.case_id}.")
            destination = next_case or case
            return redirect("review-case", bundle_id=case.bundle_id, case_id=destination.case_id)
    else:
        form = AssessmentForm(
            case.packet,
            initial=AssessmentForm.initial_for_packet(case.packet, case.assessment, case.comparison),
        )
    criterion_rows = [
        {
            "criterion": criterion,
            "automated": form.automated_by_id.get(criterion["id"]),
            "disposition": form[f"disposition_{position}"] if form.automated else None,
            "status": form[f"status_{position}"],
            "reason": form[f"reason_{position}"],
            "refs": form[f"refs_{position}"],
        }
        for position, criterion in enumerate(case.packet["rubric"]["criteria"])
    ]
    return render(
        request,
        "reviews/review_case.html",
        {
            "case": case,
            "bundle": case.bundle,
            "criterion_rows": criterion_rows,
            "progress_field": form["progress_score"] if "progress_score" in form.fields else None,
            "previous_case": previous_case,
            "next_case": next_case,
        },
    )


def export_bundle(request, bundle_id):
    bundle = get_object_or_404(ReviewBundle, pk=bundle_id)
    cases = list(bundle.cases.all())
    if not cases or any(not case.completed for case in cases):
        messages.error(request, "Complete every case before exporting assessments.")
        return redirect("bundle", bundle_id=bundle.pk)
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for case in cases:
            payload = case.assessment
            if bundle.review_mode == "model_assisted_error_audit_v1":
                payload = {
                    "review_mode": bundle.review_mode,
                    "automated_result": case.packet["automated_result"],
                    "assessment": case.assessment,
                    "difference_manifest": case.comparison,
                }
            archive.writestr(
                f"case-{case.case_id}-assessment.json",
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )
        if bundle.review_mode == "model_assisted_error_audit_v1":
            archive.writestr(
                "assisted-review-audit.json",
                json.dumps(
                    {
                        "review_mode": bundle.review_mode,
                        "plan_hash": bundle.plan_hash,
                        "cases": [
                            {"case_id": case.case_id, "case_hash": case.case_hash, **case.comparison}
                            for case in cases
                        ],
                        "notice": "Model-assisted error audit; not an independent blinded human calibration.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
            )
    content.seek(0)
    return FileResponse(
        content,
        as_attachment=True,
        filename=f"{bundle.display_name.replace(' ', '-')}-assessments.zip",
        content_type="application/zip",
    )


def delete_bundle(request, bundle_id):
    if request.method != "POST":
        raise Http404
    bundle = get_object_or_404(ReviewBundle, pk=bundle_id)
    bundle.delete()
    messages.success(request, "The local packet copy and saved assessments were deleted.")
    return redirect(reverse("home"))
