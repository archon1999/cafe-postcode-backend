from copy import deepcopy

from django.db import migrations
from django.db.models import Max


def replace_service_fee_labels(layout):
    changed = False
    for block in layout.get('blocks', []):
        for row in block.get('rows', []):
            label = row.get('label', '')
            if not isinstance(label, str):
                continue
            for scope in ('restaurant', 'hall', 'table'):
                tokens = ('{{totals.' + scope + 'ServiceFeeRateLabel}}',
                          '{{totals.' + scope + 'ServiceFeePercent}}%')
                if any(token in label for token in tokens):
                    row['label'] = '{{totals.' + scope + 'ServiceFeeLabel}}'
                    changed = True
                    break
    return changed


def publish_service_fee_labels(apps, schema_editor):
    PrintTemplate = apps.get_model("printing", "PrintTemplate")
    PrintTemplateVersion = apps.get_model("printing", "PrintTemplateVersion")

    alias = schema_editor.connection.alias
    templates = PrintTemplate.objects.using(alias).filter(
        kind__in=["order_precheck", "payment_receipt_plain", "payment_receipt_fiscal"],
        published_version__isnull=False,
    ).select_related("published_version")

    for template in templates.iterator():
        previous = template.published_version
        layout = deepcopy(previous.layout)
        if not replace_service_fee_labels(layout):
            continue

        revision = (
            template.versions.using(alias).aggregate(value=Max("revision"))["value"] or 0
        ) + 1
        version = PrintTemplateVersion.objects.using(alias).create(
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
        previous.save(using=alias, update_fields=("status", "updated_at"))
        template.published_version = version
        template.save(using=alias, update_fields=("published_version", "updated_at"))


def restore_service_fee_labels(apps, schema_editor):
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')
    alias = schema_editor.connection.alias
    targets = []
    for template in PrintTemplate.objects.using(alias).filter(
        kind__in=['order_precheck', 'payment_receipt_plain', 'payment_receipt_fiscal'],
        published_version__isnull=False,
    ).select_related('published_version').iterator():
        current = template.published_version
        has_new_labels = any(
            '{{totals.' + scope + 'ServiceFeeLabel}}' in str(row.get('label', ''))
            for block in current.layout.get('blocks', []) for row in block.get('rows', [])
            for scope in ('restaurant', 'hall', 'table')
        )
        if not has_new_labels:
            continue
        previous = PrintTemplateVersion.objects.using(alias).filter(
            template_id=template.pk, revision=current.revision - 1, status='retired',
        ).first()
        expected = deepcopy(previous.layout) if previous else {}
        if not previous or not replace_service_fee_labels(expected) or expected != current.layout:
            raise RuntimeError(
                f'Cannot reverse receipt labels: template {template.pk} was edited. '
                'Restore its reviewed pre-release published version first.'
            )
        targets.append((template, current, previous))
    for template, current, previous in targets:
        current.status = 'retired'
        current.save(using=alias, update_fields=('status', 'updated_at'))
        previous.status = 'published'
        previous.save(using=alias, update_fields=('status', 'updated_at'))
        template.published_version = previous
        template.save(using=alias, update_fields=('published_version', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [("printing", "0014_publish_item_line_totals")]

    operations = [
        migrations.RunPython(
            publish_service_fee_labels, restore_service_fee_labels
        ),
    ]
