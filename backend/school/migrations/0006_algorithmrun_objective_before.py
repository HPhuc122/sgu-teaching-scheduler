from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("school", "0005_algorithmrun_scheduleentry_algorithm_run")]

    operations = [
        migrations.AddField(
            model_name="algorithmrun",
            name="objective_before",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
