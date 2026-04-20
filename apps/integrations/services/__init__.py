from .config_resolver import IntegrationConfigResolverService
from .fiscal_drive import FiscalDriveIntegrationService, SUPPORTED_FISCAL_PROVIDERS
from .mock_fiscal import MockFiscalIntegrationService
from .mock_payment import MockPaymentIntegrationService
from .mock_printer import MockPrinterIntegrationService
from .qz_tray_printer import QzTrayPrinterIntegrationService
from .windows_raw_printer import WindowsRawPrinterIntegrationService


def ensure_mock_configs(restaurant):
    resolver_service = IntegrationConfigResolverService()
    resolver_service.ensure_mock_configs(restaurant=restaurant)


def charge_payment(order, payment):
    return MockPaymentIntegrationService().charge_payment(order=order, payment=payment)


def refund_payment(payment, reason=''):
    return MockPaymentIntegrationService().refund_payment(payment=payment, reason=reason)


def _get_fiscal_service(*, restaurant):
    config = IntegrationConfigResolverService().get_config(kind='fiscal', restaurant=restaurant)
    if config is None or config.mode != 'live':
        return MockFiscalIntegrationService(), config

    provider = str(config.provider or '').strip()
    if provider in SUPPORTED_FISCAL_PROVIDERS:
        return FiscalDriveIntegrationService(config), config
    if provider in {'mock', 'mock-fiscal'}:
        return MockFiscalIntegrationService(), config
    raise ValueError(f"Unsupported fiscal provider '{provider}'.")


def _serialize_fiscal_error(*, config, error):
    return {
        'ok': False,
        'provider': getattr(config, 'provider', 'mock-fiscal') if config is not None else 'mock-fiscal',
        'mode': getattr(config, 'mode', 'mock') if config is not None else 'mock',
        'detail': str(error),
    }


def issue_fiscal_receipt(order, payment):
    try:
        service, config = _get_fiscal_service(restaurant=order.restaurant)
        return service.issue_receipt(order=order, payment=payment)
    except Exception as error:
        return _serialize_fiscal_error(config=locals().get('config'), error=error)


def reprint_fiscal_receipt(receipt):
    try:
        service, config = _get_fiscal_service(restaurant=receipt.order.restaurant)
        return service.reprint_receipt(receipt=receipt)
    except Exception as error:
        return _serialize_fiscal_error(config=locals().get('config'), error=error)


def issue_refund_receipt(order, payment, refund):
    try:
        service, config = _get_fiscal_service(restaurant=order.restaurant)
        return service.issue_refund_receipt(order=order, payment=payment, refund=refund)
    except Exception as error:
        return _serialize_fiscal_error(config=locals().get('config'), error=error)


def print_kitchen_ticket(ticket):
    return MockPrinterIntegrationService().print_ticket(ticket=ticket)


def print_prebill(order, payload):
    config = IntegrationConfigResolverService().get_config(kind='printer', restaurant=order.restaurant)
    if config is None or config.mode != 'live':
        raise ValueError('Live printer integration is not configured.')

    if config.provider == 'qz-tray':
        service = QzTrayPrinterIntegrationService(config)
    elif config.provider == 'windows-raw':
        service = WindowsRawPrinterIntegrationService(config)
    elif config.provider == 'mock-printer':
        service = MockPrinterIntegrationService(config=config)
    else:
        raise ValueError(f"Unsupported printer provider '{config.provider}'.")

    try:
        return service.print_prebill(order=order, payload=payload)
    except ValueError:
        raise
    except Exception as error:
        return {
            'ok': False,
            'provider': config.provider,
            'mode': config.mode,
            'detail': str(error),
        }
