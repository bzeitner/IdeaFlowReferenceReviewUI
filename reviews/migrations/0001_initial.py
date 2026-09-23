from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="ReviewBundle",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("display_name", models.CharField(max_length=120)),
                ("source_name", models.CharField(max_length=255)),
                ("plan_hash", models.CharField(max_length=64)),
                ("rubric_hash", models.CharField(max_length=64)),
                ("review_mode", models.CharField(default="independent_blinded_v1", max_length=40)),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-imported_at"]},
        ),
        migrations.CreateModel(
            name="ReviewCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("case_id", models.PositiveBigIntegerField()),
                ("case_hash", models.CharField(max_length=64)),
                ("position", models.PositiveIntegerField()),
                ("packet", models.JSONField()),
                ("assessment", models.JSONField(blank=True, default=dict)),
                ("comparison", models.JSONField(blank=True, default=dict)),
                ("completed", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bundle", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cases", to="reviews.reviewbundle")),
            ],
            options={"ordering": ["position"]},
        ),
        migrations.AddConstraint(
            model_name="reviewcase",
            constraint=models.UniqueConstraint(fields=("bundle", "case_id"), name="unique_bundle_case"),
        ),
    ]
