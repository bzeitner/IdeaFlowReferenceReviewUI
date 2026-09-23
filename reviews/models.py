import uuid

from django.db import models


class ReviewBundle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=120)
    source_name = models.CharField(max_length=255)
    plan_hash = models.CharField(max_length=64)
    rubric_hash = models.CharField(max_length=64)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]

    @property
    def completed_count(self):
        return self.cases.filter(completed=True).count()

    @property
    def case_count(self):
        return self.cases.count()


class ReviewCase(models.Model):
    bundle = models.ForeignKey(ReviewBundle, related_name="cases", on_delete=models.CASCADE)
    case_id = models.PositiveBigIntegerField()
    case_hash = models.CharField(max_length=64)
    position = models.PositiveIntegerField()
    packet = models.JSONField()
    assessment = models.JSONField(default=dict, blank=True)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["bundle", "case_id"], name="unique_bundle_case")]
