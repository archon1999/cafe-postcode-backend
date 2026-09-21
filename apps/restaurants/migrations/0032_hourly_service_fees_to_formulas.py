from django.db import migrations


SCOPES = [('restaurants', 'Restaurant'), ('floor', 'Hall'), ('floor', 'DiningTable')]


def legacy_definition(rate):
    from common.service_fee_formulas.catalog import normalize_definition

    return normalize_definition({
        'name': 'Soatlik xizmat haqi',
        'source': 'round_money(hourly_rate * max(60, floor(duration_minutes / 5) * 5) / 60, 1000, "half_down")',
        'parameters': {'hourly_rate': str(rate)},
        'timezone': 'Asia/Tashkent',
    })


def migrate_hourly_settings(apps, schema_editor):
    # Existing orders/sessions keep their original snapshots and rounding rules.
    for app_label, model_name in SCOPES:
        model = apps.get_model(app_label, model_name)
        rows = model.objects.using(schema_editor.connection.alias).filter(service_fee_mode='hourly')
        for row in rows.iterator():
            definition = legacy_definition(row.service_fee_hourly_rate)
            model.objects.using(schema_editor.connection.alias).filter(pk=row.pk).update(
                service_fee_mode='formula', service_fee_formula=definition,
            )


def restore_hourly_settings(apps, schema_editor):
    # Old application versions cannot read formula snapshots, even if the
    # restaurant settings themselves can be restored. Preserve billing history.
    for app_label, model_name in [('floor', 'TableSession'), ('sales', 'Order')]:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        for pk, snapshot in model.objects.using(schema_editor.connection.alias).exclude(
            service_fee_snapshot=[],
        ).values_list('pk', 'service_fee_snapshot').iterator():
            if any(part.get('mode') == 'formula' for part in (snapshot or []) if isinstance(part, dict)):
                raise RuntimeError(
                    f'Cannot reverse service fee migration: {app_label}.{model_name} {pk} '
                    'has formula billing history. Keep the formula-capable runtime and roll back only new assignments.'
                )
    # Preflight every scope before writing: never overwrite a later custom tariff.
    targets = []
    for app_label, model_name in SCOPES:
        model = apps.get_model(app_label, model_name)
        rows = model.objects.using(schema_editor.connection.alias).filter(service_fee_mode='formula')
        for row in rows.iterator():
            if row.service_fee_formula != legacy_definition(row.service_fee_hourly_rate):
                raise RuntimeError(
                    f'Cannot reverse service fee migration: {app_label}.{model_name} {row.pk} '
                    'has a custom or modified formula. Restore its reviewed pre-release settings first.'
                )
            targets.append((model, row.pk))
    for model, pk in targets:
        model.objects.using(schema_editor.connection.alias).filter(pk=pk).update(
            service_fee_mode='hourly', service_fee_formula={},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0031_service_fee_formulas'),
        ('floor', '0009_service_fee_formulas'),
    ]
    operations = [migrations.RunPython(migrate_hourly_settings, restore_hourly_settings)]
