from copy import deepcopy

from django.db import migrations
from django.db.models import Max


RATE_LABEL_REPLACEMENTS = {
    "{{totals.restaurantServiceFeePercent}}%": "{{totals.restaurantServiceFeeRateLabel}}",
    "{{totals.hallServiceFeePercent}}%": "{{totals.hallServiceFeeRateLabel}}",
    "{{totals.tableServiceFeePercent}}%": "{{totals.tableServiceFeeRateLabel}}",
}


def replace_service_fee_rate_labels(layout):
    changed = False
    for block in layout.get("blocks", []):
        rows = block.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            label = row.get("label")
            if not isinstance(label, str):
                continue
            updated_label = label
            for old_token, new_token in RATE_LABEL_REPLACEMENTS.items():
                updated_label = updated_label.replace(old_token, new_token)
            if updated_label != label:
                row["label"] = updated_label
                changed = True
    return changed


def publish_service_fee_rate_labels(apps, schema_editor):
    PrintTemplate = apps.get_model("printing", "PrintTemplate")
    PrintTemplateVersion = apps.get_model("printing", "PrintTemplateVersion")

    templates = PrintTemplate.objects.filter(
        kind__in=["order_precheck", "payment_receipt_plain", "payment_receipt_fiscal"],
        published_version__isnull=False,
    ).select_related("published_version")

    for template in templates.iterator():
        previous = template.published_version
        layout = deepcopy(previous.layout)
        if not replace_service_fee_rate_labels(layout):
            continue

        revision = (
            template.versions.aggregate(value=Max("revision"))["value"] or 0
        ) + 1
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=revision,
            schema_version=1,
            status="published",
            preset_key=previous.preset_key,
            layout=layout,
            created_by_id=previous.created_by_id,
            published_at=previous.published_at,
        )
        previous.status = "retired"
        previous.save(update_fields=("status", "updated_at"))
        template.published_version = version
        template.save(update_fields=("published_version", "updated_at"))


class Migration(migrations.Migration):
    dependencies = [("printing", "0012_publish_unit_prices_on_payment_receipts")]

    operations = [
        migrations.RunPython(
            publish_service_fee_rate_labels, migrations.RunPython.noop
        ),
    ]
