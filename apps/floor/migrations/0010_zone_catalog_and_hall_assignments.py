from django.db import migrations, models
import django.db.models.deletion


def backfill_zone_catalog_and_hall_assignments(apps, schema_editor):
    Hall = apps.get_model('floor', 'Hall')
    ZoneOrCabin = apps.get_model('floor', 'ZoneOrCabin')

    for zone in ZoneOrCabin.objects.select_related('hall', 'hall__restaurant').iterator():
        hall = getattr(zone, 'hall', None)
        if hall is None:
            continue
        if zone.restaurant_id is None:
            ZoneOrCabin.objects.filter(pk=zone.pk).update(restaurant_id=hall.restaurant_id)

    hall_zone_map: dict[str, list[str]] = {}
    for zone in ZoneOrCabin.objects.select_related('hall').iterator():
        if zone.hall_id is None:
            continue
        hall_zone_map.setdefault(str(zone.hall_id), []).append(str(zone.pk))

    invalid_halls: list[str] = []
    for hall in Hall.objects.iterator():
        zone_ids = hall_zone_map.get(str(hall.pk), [])
        if len(zone_ids) != 1:
            invalid_halls.append(f'{hall.pk} ({len(zone_ids)} zones)')

    if invalid_halls:
        joined = ', '.join(invalid_halls)
        raise RuntimeError(f'Each hall must have exactly one assigned zone or cabin before migration: {joined}')

    for hall in Hall.objects.iterator():
        Hall.objects.filter(pk=hall.pk).update(zone_or_cabin_id=hall_zone_map[str(hall.pk)][0])


class Migration(migrations.Migration):
    dependencies = [
        ('organizations', '0008_branch_legal_name_branch_tax_number_and_more'),
        ('floor', '0009_remove_tablesession_tablesess_branch_status_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='zoneorcabin',
            name='restaurant',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='zones',
                to='organizations.restaurant',
            ),
        ),
        migrations.AddField(
            model_name='hall',
            name='zone_or_cabin',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='halls',
                to='floor.zoneorcabin',
            ),
        ),
        migrations.RunPython(backfill_zone_catalog_and_hall_assignments, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='zoneorcabin',
            name='restaurant',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='zones',
                to='organizations.restaurant',
            ),
        ),
        migrations.AlterField(
            model_name='hall',
            name='zone_or_cabin',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='halls',
                to='floor.zoneorcabin',
            ),
        ),
        migrations.RemoveField(
            model_name='hall',
            name='restaurant',
        ),
        migrations.RemoveField(
            model_name='zoneorcabin',
            name='hall',
        ),
        migrations.RemoveField(
            model_name='zoneorcabin',
            name='is_private',
        ),
        migrations.DeleteModel(
            name='LayoutObject',
        ),
        migrations.DeleteModel(
            name='LayoutTemplate',
        ),
    ]
