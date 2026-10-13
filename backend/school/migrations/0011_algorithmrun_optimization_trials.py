from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("school", "0010_algorithmrun_demand_snapshot_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="algorithmrun",
            name="optimization_trials",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
