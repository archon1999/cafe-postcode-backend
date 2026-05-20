from django.utils import timezone

from .agent_marta import MartaSoftPOSAgentPaymentService
from .config_resolver import IntegrationConfigResolverService
from .marta_softpos import MartaSoftPOSPaymentService, SUPPORTED_MARTA_PAYMENT_PROVIDERS
from .mock_payment import MockPaymentIntegrationService
from .unikassa import UnikassaFiscalIntegrationService, SUPPORTED_UNIKASSA_FISCAL_PROVIDERS, UnikassaFiscalError
from .windows_raw_printer import WindowsRawPrinterIntegrationService


PRINTER_NOT_CONFIGURED = 'PRINTER_NOT_CONFIGURED'
PRINTER_UNAVAILABLE = 'PRINTER_UNAVAILABLE'


def charge_payment(order, payment, *, manual_card_override=False, manual_card_reason=''):
    if payment.method == payment.Method.CASH:
        return {
            'ok': True,
            'provider': 'cash',
            'method': payment.method,
            'reference': '',
        }
    if payment.method == payment.Method.CARD and manual_card_override:
        return {
            'ok': True,
            'provider': 'manual-card',
            'method': payment.method,
            'reference': '',
            'manual': True,
            'reason': manual_card_reason or 'Cashier completed card payment manually after terminal failure.',
        }
    if payment.method == payment.Method.QR:
        return {
            'ok': True,
            'provider': 'manual-qr',
            'method': payment.method,
            'reference': '',
            'manual': True,
            'detail': 'QR integration is not automated yet.',
        }
    try:
        service, _config = _get_payment_service(order=order, payment=payment)
        return service.charge_payment(order=order, payment=payment)
    except Exception as error:
        return {
            'ok': False,
            'provider': 'marta-softpos' if payment.method == payment.Method.CARD else 'mock-payment',
            'method': payment.method,
            'detail': str(error),
        }


def refund_payment(payment, reason=''):
    return MockPaymentIntegrationService().refund_payment(payment=payment, reason=reason)


def _get_enabled_integration_config(*, restaurant, kind, provider=None):
    queryset = IntegrationConfigResolverService().get_queryset(kind=kind, restaurant=restaurant)
    if provider is not None:
        queryset = queryset.filter(provider=provider)
    return queryset.order_by('-created_at').first()


def _get_payment_service(*, order, payment):
    marta_config = None
    cash_desk = getattr(payment, 'cash_desk', None)
    if cash_desk is not None:
        marta_config = getattr(cash_desk, 'payment_integration', None)
        if marta_config is not None and (
            marta_config.kind != 'payment'
            or marta_config.provider != 'marta-softpos'
            or not marta_config.is_enabled
        ):
            marta_config = None
    if (
        payment.method == payment.Method.CARD
        and marta_config is not None
        and str(marta_config.provider or '').strip() in SUPPORTED_MARTA_PAYMENT_PROVIDERS
    ):
        return MartaSoftPOSAgentPaymentService(marta_config), marta_config

    raise ValueError('MARTA SoftPOS payment integration is not configured for the active cash desk.')


def _get_fiscal_service(*, restaurant, cash_desk=None):
    config = _get_fiscal_config(restaurant=restaurant, cash_desk=cash_desk)
    return _build_fiscal_service(config), config


def _get_fiscal_config(*, restaurant, cash_desk=None):
    config = None
    if cash_desk is not None:
        config = getattr(cash_desk, 'fiscal_integration', None)
        if config is not None and (config.kind != 'fiscal' or not config.is_enabled):
            config = None
    if config is None:
        config = IntegrationConfigResolverService().get_config(kind='fiscal', restaurant=restaurant)
    if config is None:
        raise ValueError('Fiscal integration is not configured.')
    return config


def _build_fiscal_service(config):
    provider = str(config.provider or '').strip()
    if provider in SUPPORTED_UNIKASSA_FISCAL_PROVIDERS:
        return UnikassaFiscalIntegrationService(config)
    raise ValueError(f"Unsupported fiscal provider '{provider}'.")


def _serialize_fiscal_error(*, config, error, split_reason=''):
    payload = {
        'ok': False,
        'provider': getattr(config, 'provider', '') if config is not None else '',
        'code': getattr(error, 'code', ''),
        'detail': str(error),
    }
    if split_reason:
        payload['split_reason'] = split_reason
    return payload


def issue_fiscal_receipt(order, payment):
    config = None
    try:
        config = _get_fiscal_config(restaurant=order.restaurant, cash_desk=getattr(payment, 'cash_desk', None))
        service = _build_fiscal_service(config)
        return service.issue_receipt(order=order, payment=payment)
    except Exception as error:
        return _serialize_fiscal_error(config=config, error=error)


def issue_fiscal_receipts(order, payment, *, split_reasons=None):
    config = None
    try:
        config = _get_fiscal_config(restaurant=order.restaurant, cash_desk=getattr(payment, 'cash_desk', None))
        service = _build_fiscal_service(config)
        if hasattr(service, 'issue_receipts'):
            return service.issue_receipts(order=order, payment=payment, split_reasons=split_reasons)
        return [service.issue_receipt(order=order, payment=payment)]
    except Exception as error:
        if split_reasons:
            return [
                _serialize_fiscal_error(config=config, error=error, split_reason=split_reason)
                for split_reason in split_reasons
            ]
        return [_serialize_fiscal_error(config=config, error=error)]


def reprint_fiscal_receipt(receipt):
    config = None
    try:
        config = _get_fiscal_config(
            restaurant=receipt.order.restaurant,
            cash_desk=getattr(getattr(receipt, 'payment', None), 'cash_desk', None),
        )
        service = _build_fiscal_service(config)
        return service.reprint_receipt(receipt=receipt)
    except Exception as error:
        return _serialize_fiscal_error(config=config, error=error)


def issue_refund_receipt(order, payment, refund):
    config = None
    try:
        config = _get_fiscal_config(restaurant=order.restaurant, cash_desk=getattr(payment, 'cash_desk', None))
        service = _build_fiscal_service(config)
        return service.issue_refund_receipt(order=order, payment=payment, refund=refund)
    except Exception as error:
        return _serialize_fiscal_error(config=config, error=error)


def open_fiscal_shift(*, restaurant, cash_desk=None):
    service, _config = _get_fiscal_service(restaurant=restaurant, cash_desk=cash_desk)
    if not hasattr(service, 'open_shift'):
        raise ValueError('Fiscal provider does not support shift open.')
    return service.open_shift(cash_desk=cash_desk)


def close_fiscal_shift(*, restaurant, cash_desk=None):
    service, _config = _get_fiscal_service(restaurant=restaurant, cash_desk=cash_desk)
    if not hasattr(service, 'close_shift'):
        raise ValueError('Fiscal provider does not support shift close.')
    return service.close_shift(cash_desk=cash_desk)


def _build_kitchen_ticket_payload(ticket):
    from apps.sales.helpers import get_order_item_model

    order = ticket.order
    OrderItem = get_order_item_model()
    items = (
        order.items.filter(prep_station=ticket.prep_station)
        .exclude(status=OrderItem.Status.CANCELLED)
        .select_related('catalog_item')
    )
    return {
        'restaurant_name': order.restaurant.name,
        'order_number': order.order_number,
        'channel_label': order.get_channel_display(),
        'table_label': getattr(getattr(order.table_session, 'table', None), 'name', '') if order.table_session_id else '',
        'waiter_name': getattr(order.opened_by, 'full_name', '') if order.opened_by_id else '',
        'printed_at_label': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M'),
        'items': [
            {
                'name': item.catalog_item.name if item.catalog_item_id else item.name_snapshot,
                'quantity': item.quantity,
                'line_total': item.line_total,
                'note': item.note,
            }
            for item in items
        ],
        'subtotal': sum(int(item.line_total or 0) for item in items),
        'service_fee': 0,
        'total': sum(int(item.line_total or 0) for item in items),
        'order_note': order.note,
    }


def print_kitchen_ticket(ticket):
    config = getattr(ticket.prep_station, 'printer_integration', None)
    if config is None:
        return _client_print_fallback(
            code=PRINTER_NOT_CONFIGURED,
            detail='Kitchen ticket printer integration is not configured.',
            provider='',
        )

    if config.provider == 'windows-raw':
        service = WindowsRawPrinterIntegrationService(config)
    else:
        return _client_print_fallback(
            code=PRINTER_NOT_CONFIGURED,
            detail=f"Unsupported printer provider '{config.provider}'.",
            provider=config.provider,
        )

    try:
        return service.print_prebill(order=ticket.order, payload=_build_kitchen_ticket_payload(ticket))
    except ValueError as error:
        return _client_print_fallback(code=PRINTER_NOT_CONFIGURED, detail=str(error), provider=config.provider)
    except Exception as error:
        return _client_print_fallback(code=PRINTER_UNAVAILABLE, detail=str(error), provider=config.provider)


def print_prebill(order, payload):
    config = IntegrationConfigResolverService().get_config(kind='printer', restaurant=order.restaurant)
    if config is None:
        return _client_print_fallback(
            code=PRINTER_NOT_CONFIGURED,
            detail='Printer integration is not configured.',
            provider='',
        )

    if config.provider == 'windows-raw':
        service = WindowsRawPrinterIntegrationService(config)
    else:
        return _client_print_fallback(
            code=PRINTER_NOT_CONFIGURED,
            detail=f"Unsupported printer provider '{config.provider}'.",
            provider=config.provider,
        )

    try:
        return service.print_prebill(order=order, payload=payload)
    except ValueError as error:
        return _client_print_fallback(code=PRINTER_NOT_CONFIGURED, detail=str(error), provider=config.provider)
    except Exception as error:
        return _client_print_fallback(code=PRINTER_UNAVAILABLE, detail=str(error), provider=config.provider)


def _client_print_fallback(*, code, detail, provider):
    return {
        'ok': False,
        'provider': provider,
        'code': code,
        'detail': detail,
        'requires_client_print': True,
    }
