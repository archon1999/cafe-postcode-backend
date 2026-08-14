from copy import deepcopy

from django.db import migrations
from django.db.models import Max


SERVICE_FEE_ROWS = (
    {
        'label': 'Restoran xizmati ({{totals.restaurantServiceFeePercent}}%)',
        'value': '{{totals.restaurantServiceFee}}',
        'format': 'money',
        'hideZero': True,
    },
    {
        'label': 'Zal xizmati ({{totals.hallServiceFeePercent}}%)',
        'value': '{{totals.hallServiceFee}}',
        'format': 'money',
        'hideZero': True,
    },
    {
        'label': 'Stol xizmati ({{totals.tableServiceFeePercent}}%)',
        'value': '{{totals.tableServiceFee}}',
        'format': 'money',
        'hideZero': True,
    },
)


def publish_separate_service_fee_rows(apps, schema_editor):
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')

    templates = PrintTemplate.objects.filter(
        kind__in=['order_precheck', 'payment_receipt_plain', 'payment_receipt_fiscal'],
        published_version__isnull=False,
    ).select_related('published_version')

    for template in templates.iterator():
        previous = template.published_version
        layout = deepcopy(previous.layout)
        changed = False
        for block in layout.get('blocks', []):
            rows = block.get('rows')
            if not isinstance(rows, list):
                continue
            updated_rows = []
            for row in rows:
                if row.get('value') != '{{totals.serviceFee}}':
                    updated_rows.append(row)
                    continue
                updated_rows.extend(deepcopy(SERVICE_FEE_ROWS))
                changed = True
            block['rows'] = updated_rows

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
    dependencies = [('printing', '0007_publish_order_zone_location')]

    operations = [
        migrations.RunPython(publish_separate_service_fee_rows, migrations.RunPython.noop),
    ]
