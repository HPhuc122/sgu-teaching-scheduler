from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("school", "0007_algorithmrun_diagnostics")]

    operations = [
        migrations.AddField(
            model_name="algorithmrun",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="algorithmrun",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ScheduleRunQueue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("courses_file", models.BinaryField()),
                ("rooms_file", models.BinaryField()),
                ("lecturers_file", models.BinaryField()),
                ("run", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                             related_name="queue_item", to="school.algorithmrun")),
                ("semester", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                                                  related_name="active_schedule_run", to="school.semester")),
            ],
            options={"db_table": "HangDoiXepLich"},
        ),
    ]
