from django.db import migrations, models


def _json_number(value):
    number = float(value or 0)
    return int(number) if number.is_integer() else number


def backfill_orders(apps, schema_editor):
    Order = apps.get_model("sales", "Order")
    for order in Order.objects.select_related("restaurant", "table_session").iterator():
        if order.channel != "hall":
            continue
        source_names = {
            "restaurant": order.restaurant.name,
            "hall": "",
            "table": "",
        }
        started_at = order.created_at
        if order.table_session_id:
            session = order.table_session
            started_at = session.opened_at or session.created_at
            source_names["hall"] = session.hall.name
            source_names["table"] = session.table.name
        components = []
        for scope, percent in (
            ("restaurant", order.restaurant_service_fee_percent),
            ("hall", order.hall_service_fee_percent),
            ("table", order.table_service_fee_percent),
        ):
            if percent and percent > 0:
                components.append(
                    {
                        "scope": scope,
                        "source_name": source_names[scope],
                        "mode": "percentage",
                        "percent": _json_number(percent),
                    }
                )
        Order.objects.filter(pk=order.pk).update(
            service_fee_snapshot=components,
            service_fee_started_at=started_at,
            service_fee_frozen_at=order.closed_at if order.status == "closed" else None,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("floor", "0007_hourly_service_fees"),
        ("sales", "0011_order_hall_service_fee_percent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="service_fee_snapshot",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="order",
            name="service_fee_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="service_fee_frozen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_orders, migrations.RunPython.noop),
    ]
