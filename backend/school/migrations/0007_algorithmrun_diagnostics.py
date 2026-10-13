from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("school", "0006_algorithmrun_objective_before")]

    operations = [
        migrations.AddField(
            model_name="algorithmrun",
            name="diagnostics",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
