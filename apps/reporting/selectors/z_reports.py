from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db.models import Q

from apps.billing.models import FiscalShiftSession
from common.api.query_params import apply_ordering, get_ordering_query_param, get_str_query_param


def get_z_report_queryset(restaurant, period, params):
    queryset = FiscalShiftSession.objects.filter(
        status=FiscalShiftSession.Status.CLOSED,
        closed_at__gte=period.start,
        closed_at__lt=period.end,
    ).select_related('cash_desk', 'closed_by', 'restaurant')
    if restaurant is not None:
        queryset = queryset.filter(restaurant=restaurant)
    cash_desk_id = get_str_query_param(params, 'cashDeskId', aliases=('cash_desk_id',))
    if cash_desk_id:
        try:
            queryset = queryset.filter(cash_desk_id=UUID(cash_desk_id))
        except ValueError:
            queryset = queryset.none()
    search = get_str_query_param(params, 'search')
    if search:
        queryset = queryset.filter(
            Q(terminal_id__icontains=search) | Q(cash_desk__name__icontains=search)
            | Q(closed_by__full_name__icontains=search)
        )
    ordering = get_ordering_query_param(params, ordering_map={
        'closedAt': 'closed_at', 'openedAt': 'opened_at',
        'cashDeskName': 'cash_desk__name', 'cashierName': 'closed_by__full_name',
        'terminalId': 'terminal_id',
    })
    return apply_ordering(queryset, (*ordering, '-id') if ordering else (), default_ordering=('-closed_at', '-id'))


def _object(value):
    return value if isinstance(value, dict) else {}


def _money(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value)) / 100
        return float(number) if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def build_z_report_row(session):
    result = _object(_object(session.close_payload).get('provider_result'))
    report = _object(_object(result.get('provider_report')).get('z_info'))
    cash = _object(report.get('TotalCash'))
    card = _object(report.get('TotalCard'))
    qr = _object(report.get('TotalQR'))

    def total(key, operation):
        if report.get(key) is not None:
            return _money(report[key])
        values = [_money(pair.get(operation)) for pair in (cash, card, qr)]
        return sum(value for value in values if value is not None) if any(value is not None for value in values) else None

    return {
        'id': str(session.id),
        'restaurant_id': str(session.restaurant_id),
        'restaurant_name': session.restaurant.name,
        'cash_desk_name': session.cash_desk.name if session.cash_desk else '',
        'cashier_name': session.closed_by.full_name if session.closed_by else '',
        'terminal_id': session.terminal_id,
        'opened_at': session.opened_at,
        'closed_at': session.closed_at,
        'cash_total': _money(cash.get('Sale')),
        'card_total': _money(card.get('Sale')),
        'qr_total': _money(qr.get('Sale')),
        'sale_total': total('TotalSaleAmount', 'Sale'),
        'refund_total': total('TotalRefundAmount', 'Refund'),
        'sale_count': report.get('TotalSaleCount'),
        'refund_count': report.get('TotalRefundCount'),
    }
