from django.db import migrations


ALIASES = {
    'endpointUrl': 'endpoint_url',
    'taxNumber': 'tax_number',
    'connectionType': 'connection_type',
    'printerName': 'printer_name',
    'codePage': 'code_page',
    'paperWidthMm': 'paper_width_mm',
    'cutAfterPrint': 'cut_after_print',
    'terminalId': 'terminal_id',
    'factoryId': 'factory_id',
}


def canonical_settings(raw):
    values = dict(raw or {})
    for alias, canonical in ALIASES.items():
        if alias in values:
            values[canonical] = values.pop(alias)
    return values


def cleanup_redundant_setup_integrations(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    PrepStation = apps.get_model('restaurants', 'PrepStation')
    generated_suffixes = (' printer', ' MARTA', ' Fiscal Drive')

    for restaurant_id in IntegrationConfig.objects.values_list('restaurant_id', flat=True).distinct().iterator():
        bound_ids = set()
        for row in CashDesk.objects.filter(restaurant_id=restaurant_id).values_list(
            'printer_integration_id', 'payment_integration_id', 'fiscal_integration_id'
        ):
            bound_ids.update(value for value in row if value)
        bound_ids.update(
            PrepStation.objects.filter(
                restaurant_id=restaurant_id,
                printer_integration_id__isnull=False,
            ).values_list('printer_integration_id', flat=True)
        )
        bound = list(IntegrationConfig.objects.filter(id__in=bound_ids))

        candidates = IntegrationConfig.objects.filter(restaurant_id=restaurant_id).exclude(id__in=bound_ids)
        for candidate in candidates.iterator():
            if not candidate.name.endswith(generated_suffixes):
                continue
            candidate_settings = canonical_settings(candidate.settings)
            for target in bound:
                target_settings = canonical_settings(target.settings)
                if (
                    candidate.kind == target.kind
                    and candidate.provider == target.provider
                    and candidate.is_enabled == target.is_enabled
                    and all(target_settings.get(key) == value for key, value in candidate_settings.items())
                ):
                    candidate.delete()
                    break


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0011_integrationconfig_name'),
        ('restaurants', '0020_remove_unikassa_provider'),
    ]

    operations = [
        migrations.RunPython(cleanup_redundant_setup_integrations, migrations.RunPython.noop),
    ]
