from django.db import migrations


def restore_legacy_80_defaults(apps, schema_editor):
    from apps.printing.presets import PRINT_KINDS, get_preset_layout

    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')
    versions = PrintTemplateVersion.objects.filter(
        template__kind__in=PRINT_KINDS,
        revision=1,
        status='published',
        preset_key='standard_80',
    ).select_related('template')
    for version in versions.iterator():
        version.preset_key = 'legacy_80'
        version.layout = get_preset_layout('legacy_80', version.template.kind)
        version.save(update_fields=('preset_key', 'layout', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [('printing', '0001_initial')]

    operations = [migrations.RunPython(restore_legacy_80_defaults, migrations.RunPython.noop)]
