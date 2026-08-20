from copy import deepcopy

from django.db import migrations
from django.db.models import Max


def remove_legacy_cashier_alias(layout):
    changed = False
    for block in layout.get('blocks', []):
        if block.get('type') != 'metadata':
            continue
        rows = block.get('rows')
        if not isinstance(rows, list):
            continue
        has_cashier_row = any(
            row.get('value') == '{{order.cashier}}' for row in rows
        )
        if not has_cashier_row:
            continue
        filtered_rows = [
            row
            for row in rows
            if not (
                str(row.get('label') or '').strip().casefold() == 'kassir'
                and row.get('value') == '{{order.waiter}}'
            )
        ]
        if len(filtered_rows) != len(rows):
            block['rows'] = filtered_rows
            changed = True
    return changed


def normalize_payment_cashier_rows(apps, schema_editor):
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')

    templates = PrintTemplate.objects.filter(
        kind__in=['payment_receipt_plain', 'payment_receipt_fiscal'],
        published_version__isnull=False,
    ).select_related('published_version')
    for template in templates.iterator():
        previous = template.published_version
        layout = deepcopy(previous.layout)
        if not remove_legacy_cashier_alias(layout):
            continue
        revision = (template.versions.aggregate(value=Max('revision'))['value'] or 0) + 1
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=revision,
            schema_version=previous.schema_version,
            status='published',
            preset_key=previous.preset_key,
            layout=layout,
            created_by_id=previous.created_by_id,
            published_at=previous.published_at,
        )
        previous.status = 'retired'
        previous.save(update_fields=('status', 'updated_at'))
        template.published_version = version
        template.save(update_fields=('published_version', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [('printing', '0010_unify_receipt_templates')]

    operations = [
        migrations.RunPython(
            normalize_payment_cashier_rows,
            migrations.RunPython.noop,
        ),
    ]
