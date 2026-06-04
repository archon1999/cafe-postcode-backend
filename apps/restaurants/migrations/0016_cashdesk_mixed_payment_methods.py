from django.db import migrations


def migrate_payment_methods(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    for cash_desk in CashDesk.objects.all().iterator():
        methods = list(dict.fromkeys(cash_desk.enabled_payment_methods or []))
        methods = [method for method in methods if method != 'qr']
        if {'cash', 'card'}.issubset(set(methods)) and 'mixed' not in methods:
            methods.append('mixed')
        if not methods:
            methods = ['cash', 'card', 'mixed']
        cash_desk.enabled_payment_methods = methods
        cash_desk.save(update_fields=['enabled_payment_methods'])


def rollback_payment_methods(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    for cash_desk in CashDesk.objects.all().iterator():
        methods = [method for method in list(dict.fromkeys(cash_desk.enabled_payment_methods or [])) if method != 'mixed']
        if {'cash', 'card'}.issubset(set(methods)) and 'qr' not in methods:
            methods.append('qr')
        if not methods:
            methods = ['cash', 'card', 'qr']
        cash_desk.enabled_payment_methods = methods
        cash_desk.save(update_fields=['enabled_payment_methods'])


class Migration(migrations.Migration):

    dependencies = [
        ('restaurants', '0015_cashdesk_printer_integration'),
    ]

    operations = [
        migrations.RunPython(migrate_payment_methods, rollback_payment_methods),
    ]
