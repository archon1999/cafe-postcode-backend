from django.db import migrations
from django.db.models import Exists, OuterRef


def convert_failed_fiscal_receipts_to_plain_payments(apps, schema_editor):
    Payment = apps.get_model('billing', 'Payment')
    Receipt = apps.get_model('billing', 'Receipt')

    sent_receipts_for_payment = Receipt.objects.filter(
        payment_id=OuterRef('pk'),
        kind='fiscal',
        status='sent',
    )
    unresolved_payment_ids = list(
        Payment.objects.filter(
            status='succeeded',
            register_fiscal=True,
        )
        .annotate(has_sent_fiscal_receipt=Exists(sent_receipts_for_payment))
        .filter(has_sent_fiscal_receipt=False)
        .values_list('id', flat=True)
    )
    if unresolved_payment_ids:
        Payment.objects.filter(id__in=unresolved_payment_ids).update(register_fiscal=False)

    failed_receipts = Receipt.objects.filter(
        kind='fiscal',
        status='failed',
        payment__isnull=False,
    ).select_related('payment')
    receipt_ids = []

    for receipt in failed_receipts.iterator():
        payment = receipt.payment
        has_sent_fiscal_receipt = Receipt.objects.filter(
            payment_id=payment.id,
            kind='fiscal',
            status='sent',
        ).exists()
        if has_sent_fiscal_receipt:
            continue
        receipt_ids.append(receipt.id)

    if receipt_ids:
        Receipt.objects.filter(id__in=receipt_ids).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0011_cashshift_next_order_number'),
    ]

    operations = [
        migrations.RunPython(convert_failed_fiscal_receipts_to_plain_payments, noop_reverse),
    ]
