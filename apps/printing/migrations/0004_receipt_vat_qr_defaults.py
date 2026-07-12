from copy import deepcopy

from django.db import migrations
from django.db.models import Max


def publish_receipt_layout_fixes(apps, schema_editor):
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')

    templates = PrintTemplate.objects.filter(
        kind__in=['payment_receipt_plain', 'payment_receipt_fiscal'],
        published_version__isnull=False,
    ).select_related('published_version')

    for template in templates.iterator():
        previous = template.published_version
        layout = deepcopy(previous.layout)
        changed = False

        for block in layout.get('blocks', []):
            if template.kind == 'payment_receipt_plain':
                if block.get('type') == 'items_table':
                    for key in ('showVat', 'vatLabel', 'vatValue'):
                        if key in block:
                            block.pop(key, None)
                            changed = True
                if isinstance(block.get('rows'), list):
                    rows = [
                        row
                        for row in block['rows']
                        if 'totals.vat' not in str(row.get('value', ''))
                        and 'QQS' not in str(row.get('label', '')).upper()
                    ]
                    if rows != block['rows']:
                        block['rows'] = rows
                        changed = True

            if template.kind == 'payment_receipt_fiscal' and block.get('type') == 'qr':
                if block.get('align') != 'center' or block.get('qrScale') != 2:
                    block['align'] = 'center'
                    block['qrScale'] = 2
                    changed = True

        if not changed:
            continue

        revision = (template.versions.aggregate(value=Max('revision'))['value'] or 0) + 1
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=revision,
            schema_version=1,
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
    dependencies = [('printing', '0003_publish_fiscal_item_vat_layout')]

    operations = [
        migrations.RunPython(publish_receipt_layout_fixes, migrations.RunPython.noop),
    ]
