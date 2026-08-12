from django.db import migrations, models
from django.utils import timezone


def create_order_precheck_templates(apps, schema_editor):
    from apps.printing.presets import get_preset_layout

    Restaurant = apps.get_model('restaurants', 'Restaurant')
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')
    now = timezone.now()
    for restaurant_id in Restaurant.objects.values_list('id', flat=True).iterator():
        template, _created = PrintTemplate.objects.get_or_create(
            restaurant_id=restaurant_id,
            kind='order_precheck',
        )
        if template.published_version_id:
            continue
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=1,
            schema_version=1,
            status='published',
            preset_key='legacy_80',
            layout=get_preset_layout('legacy_80', 'order_precheck'),
            published_at=now,
        )
        template.published_version_id = version.id
        template.save(update_fields=('published_version', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [('printing', '0005_shift_report_template')]

    operations = [
        migrations.AlterField(
            model_name='printtemplate',
            name='kind',
            field=models.CharField(
                choices=[
                    ('kitchen_ticket', 'Kitchen ticket'),
                    ('order_precheck', 'Order precheck'),
                    ('payment_receipt_plain', 'Plain payment receipt'),
                    ('payment_receipt_fiscal', 'Fiscal payment receipt'),
                    ('shift_report', 'Shift report'),
                ],
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name='printdocument',
            name='kind',
            field=models.CharField(
                choices=[
                    ('kitchen_ticket', 'Kitchen ticket'),
                    ('order_precheck', 'Order precheck'),
                    ('payment_receipt_plain', 'Plain payment receipt'),
                    ('payment_receipt_fiscal', 'Fiscal payment receipt'),
                    ('shift_report', 'Shift report'),
                ],
                max_length=40,
            ),
        ),
        migrations.RunPython(create_order_precheck_templates, migrations.RunPython.noop),
    ]
