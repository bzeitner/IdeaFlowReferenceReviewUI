from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reviews", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="reviewbundle",
            name="review_mode",
            field=models.CharField(default="independent_blinded_v1", max_length=40),
        ),
        migrations.AddField(
            model_name="reviewcase",
            name="comparison",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
