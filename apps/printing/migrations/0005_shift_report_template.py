from django.db import migrations, models
from django.utils import timezone


def create_shift_report_templates(apps, schema_editor):
    from apps.printing.presets import get_shift_report_layout

    Restaurant = apps.get_model('restaurants', 'Restaurant')
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')
    now = timezone.now()
    for restaurant_id in Restaurant.objects.values_list('id', flat=True).iterator():
        template, _created = PrintTemplate.objects.get_or_create(
            restaurant_id=restaurant_id,
            kind='shift_report',
        )
        if template.published_version_id:
            continue
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=1,
            schema_version=1,
            status='published',
            preset_key='internal_shift_report_80',
            layout=get_shift_report_layout(),
            published_at=now,
        )
        template.published_version_id = version.id
        template.save(update_fields=('published_version', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [('printing', '0004_receipt_vat_qr_defaults')]

    operations = [
        migrations.AlterField(
            model_name='printtemplate',
            name='kind',
            field=models.CharField(
                choices=[
                    ('kitchen_ticket', 'Kitchen ticket'),
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
                    ('payment_receipt_plain', 'Plain payment receipt'),
                    ('payment_receipt_fiscal', 'Fiscal payment receipt'),
                    ('shift_report', 'Shift report'),
                ],
                max_length=40,
            ),
        ),
        migrations.RunPython(create_shift_report_templates, migrations.RunPython.noop),
    ]
