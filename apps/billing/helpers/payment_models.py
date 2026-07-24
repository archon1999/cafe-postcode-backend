from django.apps import apps


def get_cash_shift_model():
    return apps.get_model('billing', 'CashShift')


def get_cash_expense_model():
    return apps.get_model('billing', 'CashExpense')


def get_expense_category_model():
    return apps.get_model('billing', 'ExpenseCategory')


def get_fiscal_shift_session_model():
    return apps.get_model('billing', 'FiscalShiftSession')


def get_payment_model():
    return apps.get_model('billing', 'Payment')


def get_payment_refund_model():
    return apps.get_model('billing', 'PaymentRefund')


def get_receipt_model():
    return apps.get_model('billing', 'Receipt')
