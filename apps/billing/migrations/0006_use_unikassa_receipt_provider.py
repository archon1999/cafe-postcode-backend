from django.db import migrations


def migrate_receipt_provider(apps, schema_editor):
    Receipt = apps.get_model('billing', 'Receipt')

    for receipt in Receipt.objects.filter(kind='fiscal', provider='fiscal-drive-service').iterator():
        payload = dict(receipt.payload or {})
        if payload.get('provider') == 'fiscal-drive-service':
            payload['provider'] = 'unikassa'
        receipt.provider = 'unikassa'
        receipt.payload = payload
        receipt.save(update_fields=('provider', 'payload', 'updated_at'))


def reverse_receipt_provider(apps, schema_editor):
    Receipt = apps.get_model('billing', 'Receipt')

    for receipt in Receipt.objects.filter(kind='fiscal', provider='unikassa').iterator():
        payload = dict(receipt.payload or {})
        if payload.get('provider') == 'unikassa':
            payload['provider'] = 'fiscal-drive-service'
        receipt.provider = 'fiscal-drive-service'
        receipt.payload = payload
        receipt.save(update_fields=('provider', 'payload', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0005_payment_register_fiscal_receipt_fiscal_metadata'),
    ]

    operations = [
        migrations.RunPython(migrate_receipt_provider, reverse_receipt_provider),
    ]
