from copy import deepcopy

from django.db import migrations
from django.db.models import Max


ZONE_VALUE = '{{order.zoneDisplay}}'


def publish_order_zone_location(apps, schema_editor):
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')

    templates = PrintTemplate.objects.filter(
        kind__in=[
            'kitchen_ticket',
            'order_precheck',
            'payment_receipt_plain',
            'payment_receipt_fiscal',
        ],
        published_version__isnull=False,
    ).select_related('published_version')

    for template in templates.iterator():
        previous = template.published_version
        layout = deepcopy(previous.layout)
        if ZONE_VALUE in str(layout):
            continue

        changed = False
        for block in layout.get('blocks', []):
            rows = block.get('rows')
            if not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                if row.get('value') == '{{order.table}}':
                    rows.insert(index + 1, {'label': 'Hudud', 'value': ZONE_VALUE})
                    changed = True
                    break
            if changed:
                break

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
    dependencies = [('printing', '0006_order_precheck_template')]

    operations = [
        migrations.RunPython(publish_order_zone_location, migrations.RunPython.noop),
    ]
