from .config_resolver import IntegrationConfigResolverService
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


def issue_fiscal_receipt(order, payment):
    return MockFiscalIntegrationService().issue_receipt(order=order, payment=payment)


def reprint_fiscal_receipt(receipt):
    return MockFiscalIntegrationService().reprint_receipt(receipt=receipt)


def issue_refund_receipt(order, payment, refund):
    return MockFiscalIntegrationService().issue_refund_receipt(order=order, payment=payment, refund=refund)


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
