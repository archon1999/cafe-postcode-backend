from dataclasses import dataclass

from apps.sales.models import OrderItem


SUPPORTED_UNIKASSA_FISCAL_PROVIDERS = frozenset({'unikassa'})


class UnikassaFiscalError(Exception):
    def __init__(self, message: str, *, code: str = ''):
        super().__init__(message)
        self.code = str(code or '')


@dataclass(slots=True)
class FiscalReceiptPart:
    items: list[OrderItem]
    service_fee: int
    pay_type: str
    split_reason: str
    received_cash: int | None = None
    received_card: int | None = None

