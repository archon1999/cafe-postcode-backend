from django.db import migrations, models
import django.utils.timezone


def _json_number(value):
    number = float(value or 0)
    return int(number) if number.is_integer() else number


def _component(scope, source):
    if source is None or not source.service_fee_enabled:
        return None
    if source.service_fee_mode == "hourly":
        if source.service_fee_hourly_rate <= 0:
            return None
        return {
            "scope": scope,
            "source_name": source.name,
            "mode": "hourly",
            "hourly_rate": int(source.service_fee_hourly_rate),
        }
    if source.service_fee_percent <= 0:
        return None
    return {
        "scope": scope,
        "source_name": source.name,
        "mode": "percentage",
        "percent": _json_number(source.service_fee_percent),
    }


def backfill_sessions(apps, schema_editor):
    TableSession = apps.get_model("floor", "TableSession")
    for session in TableSession.objects.select_related(
        "restaurant", "hall", "table"
    ).iterator():
        components = [
            component
            for component in (
                _component("restaurant", session.restaurant),
                _component("hall", session.hall),
                _component("table", session.table),
            )
            if component is not None
        ]
        TableSession.objects.filter(pk=session.pk).update(
            opened_at=session.created_at,
            service_fee_snapshot=components,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("restaurants", "0027_service_fee_modes"),
        ("floor", "0006_tablesessiontable"),
    ]

    operations = [
        migrations.AddField(
            model_name="hall",
            name="service_fee_mode",
            field=models.CharField(
                choices=[("percentage", "Percentage"), ("hourly", "Hourly")],
                default="percentage",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="hall",
            name="service_fee_hourly_rate",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="diningtable",
            name="service_fee_mode",
            field=models.CharField(
                choices=[("percentage", "Percentage"), ("hourly", "Hourly")],
                default="percentage",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="diningtable",
            name="service_fee_hourly_rate",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="tablesession",
            name="opened_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="tablesession",
            name="service_fee_snapshot",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill_sessions, migrations.RunPython.noop),
    ]
