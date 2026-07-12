from django.db import migrations


def publish_fiscal_item_vat_layout(apps, schema_editor):
    from apps.printing.presets import get_preset_layout

    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')
    templates = PrintTemplate.objects.filter(
        kind='payment_receipt_fiscal',
        published_version__preset_key='legacy_80',
        published_version__revision=1,
    ).select_related('published_version')

    for template in templates.iterator():
        previous = template.published_version
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=2,
            schema_version=1,
            status='published',
            preset_key='legacy_80',
            layout=get_preset_layout('legacy_80', 'payment_receipt_fiscal'),
            created_by_id=previous.created_by_id,
            published_at=previous.published_at,
        )
        previous.status = 'retired'
        previous.save(update_fields=('status', 'updated_at'))
        template.published_version = version
        template.save(update_fields=('published_version', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [('printing', '0002_restore_legacy_80_defaults')]

    operations = [
        migrations.RunPython(publish_fiscal_item_vat_layout, migrations.RunPython.noop),
    ]
