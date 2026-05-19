from django.db import migrations


def _payload_requires_marking(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    value = payload.get('label')
    if value is None:
        value = payload.get('Label')
    return str(value).strip().lower() in {'1', 'true', 'yes'}


def _payload_gtin(payload) -> str:
    if not isinstance(payload, dict):
        return ''
    for key in ('gtin', 'GTIN', 'barcode', 'Barcode', 'barCode', 'internationalCode', 'international_code'):
        value = payload.get(key)
        digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
        if digits:
            return digits[:32]
    return ''


def forwards(apps, schema_editor):
    CatalogItem = apps.get_model('catalog', 'CatalogItem')
    for item in CatalogItem.objects.only('id', 'mxik_payload', 'requires_marking', 'marking_gtin').iterator():
        updates = []
        if _payload_requires_marking(item.mxik_payload) and not item.requires_marking:
            item.requires_marking = True
            updates.append('requires_marking')
        if not item.marking_gtin:
            gtin = _payload_gtin(item.mxik_payload)
            if gtin:
                item.marking_gtin = gtin
                updates.append('marking_gtin')
        if updates:
            item.save(update_fields=updates)


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0006_catalogitem_marking'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
