from datetime import timedelta

from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.api.throttling import LocalAgentRateThrottle

from apps.catalog.models import CatalogCategory, CatalogItem
from apps.catalog.serializers import CatalogMenuCategorySerializer
from apps.catalog.selectors import active_modifier_assignments_prefetch
from apps.billing.models import CashExpense, CashShift, ExpenseCategory
from apps.billing.serializers import CashExpenseSerializer, CashShiftSerializer
from apps.billing.services import CashExpenseService
from apps.floor.api.admin.serializers import HallSerializer, TableSessionSerializer
from apps.floor.models import TableSession
from apps.floor.selectors.pos_halls import pos_hall_queryset
from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.device_state import pos_device_state_snapshot
from apps.local_agents.selectors import bootstrap_kitchen_tickets
from apps.integrations.models import IntegrationConfig
from apps.kitchen.api.pos.serializers import KitchenTicketSerializer
from apps.printing.models import PrintTemplate
from apps.printing.services import ensure_restaurant_templates
from apps.restaurants.models import CashDesk, PrepStation
from apps.sales.models import Order
from apps.sales.serializers import OrderSerializer
from apps.users.api.pos.serializers import PosRestaurantContextSerializer, PosSessionSerializer
from apps.users.models import User


OFFLINE_RBAC_GRACE = timedelta(hours=24)


def _menu_snapshot(restaurant):
    items = CatalogItem.objects.filter(is_active=True, is_stoplisted=False).select_related(
        'category__prep_station',
        'prep_station',
    ).prefetch_related(active_modifier_assignments_prefetch())
    categories = (
        CatalogCategory.objects.filter(restaurant=restaurant, is_active=True)
        .select_related('prep_station')
        .prefetch_related(Prefetch('items', queryset=items, to_attr='active_menu_items'))
        .order_by('sort_order', 'name')
    )
    return CatalogMenuCategorySerializer(categories, many=True).data


def _hall_snapshot(restaurant):
    return HallSerializer(pos_hall_queryset(restaurant=restaurant), many=True).data


def _order_snapshot(restaurant, now):
    active_statuses = [Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY]
    orders = (
        Order.objects.filter(restaurant=restaurant)
        .filter(Q(status__in=active_statuses) | Q(closed_at__gte=now - timedelta(days=1)))
        .select_related(
            'restaurant',
            'table_session',
            'table_session__hall',
            'table_session__table',
            'opened_by',
            'cashier',
        )
        .prefetch_related(
            'items__catalog_item',
            'items__prep_station',
            'items__kitchen_ticket_line__ticket',
            'items__markings',
            'payments',
            'receipts',
        )
        .order_by('created_at')
    )
    return OrderSerializer(orders, many=True).data


def _table_session_snapshot(restaurant):
    sessions = (
        TableSession.objects.filter(
            restaurant=restaurant,
            status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
        )
        .select_related('restaurant', 'table', 'hall', 'opened_by', 'assigned_waiter')
        .order_by('created_at')
    )
    return TableSessionSerializer(sessions, many=True).data


def _kitchen_snapshot(restaurant):
    tickets = bootstrap_kitchen_tickets(restaurant=restaurant)
    return KitchenTicketSerializer(tickets, many=True).data


def _cash_shift_snapshot(restaurant):
    shifts = (
        CashShift.objects.filter(cash_desk__restaurant=restaurant, status=CashShift.Status.OPEN)
        .select_related('cash_desk', 'cashier', 'opened_by', 'closed_by')
        .order_by('opened_at')
    )
    rows = CashShiftSerializer(shifts, many=True).data
    return [
        {
            'id': str(row['id']),
            'cashDesk': str(row['cash_desk']),
            'cashDeskName': row['cash_desk_name'],
            'cashier': str(row['cashier'] or ''),
            'cashierName': row['cashier_name'],
            'openedBy': str(row['opened_by']),
            'openedByName': row['opened_by_name'],
            'closedBy': str(row['closed_by'] or ''),
            'status': row['status'],
            'openedAt': row['opened_at'],
            'closedAt': row['closed_at'],
            'openingCashAmount': row['opening_cash_amount'],
            'actualClosingCashAmount': row['actual_closing_cash_amount'],
            'expectedClosingCashAmount': row['expected_closing_cash_amount'],
            'cashDifferenceAmount': row['cash_difference_amount'],
            'cashTotal': row['cash_total'],
            'cardTotal': row['card_total'],
            'cashPrecheckTotal': row['cash_precheck_total'],
            'cashReceiptTotal': row['cash_receipt_total'],
            'cardPrecheckTotal': row['card_precheck_total'],
            'cardReceiptTotal': row['card_receipt_total'],
            'qrTotal': row['qr_total'],
            'refundTotal': row['refund_total'],
            'expenseTotal': row['expense_total'],
            'saleCount': row['sale_count'],
            'refundCount': row['refund_count'],
            'totalSaleAmount': row['total_sale_amount'],
            'cashRefundTotal': row['cash_refund_total'],
            'cardRefundTotal': row['card_refund_total'],
            'qrRefundTotal': row['qr_refund_total'],
            'vatSaleTotal': row['vat_sale_total'],
            'vatRefundTotal': row['vat_refund_total'],
            'firstReceipt': row['first_receipt'],
            'lastReceipt': row['last_receipt'],
            'receiptCount': row['receipt_count'],
            'reprintCount': row['reprint_count'],
            'nextOrderNumber': row['next_order_number'],
            'notesOpen': row['notes_open'],
            'notesClose': row['notes_close'],
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at'],
        }
        for row in rows
    ]


def _expense_snapshot(restaurant):
    categories = ExpenseCategory.objects.filter(restaurant=restaurant).order_by('sort_order', 'name')
    recipients = CashExpenseService().get_available_recipients(restaurant=restaurant)
    expenses = (
        CashExpense.objects.filter(restaurant=restaurant, cash_shift__status=CashShift.Status.OPEN)
        .select_related('cash_shift', 'cash_desk', 'category', 'recipient', 'created_by', 'voided_by')
        .order_by('occurred_at')
    )
    rows = CashExpenseSerializer(expenses, many=True).data
    return {
        'categories': [
            {
                'id': str(category.id),
                'name': category.name,
                'isActive': category.is_active,
                'sortOrder': category.sort_order,
                'createdAt': category.created_at,
                'updatedAt': category.updated_at,
            }
            for category in categories
        ],
        'recipients': [
            {
                'id': str(user.id),
                'fullName': user.full_name,
                'username': user.username,
            }
            for user in recipients
        ],
        'expenses': [
            {
                'id': str(row['id']),
                'cashShiftId': str(row['cash_shift_id']),
                'cashDesk': str(row['cash_desk']),
                'cashDeskName': row['cash_desk_name'],
                'category': str(row['category']),
                'categoryName': row['category_name'],
                'amount': row['amount'],
                'comment': row['comment'],
                'recipient': str(row['recipient'] or ''),
                'recipientName': row['recipient_name'],
                'createdBy': str(row['created_by']),
                'createdByName': row['created_by_name'],
                'status': row['status'],
                'occurredAt': row['occurred_at'],
                'voidedAt': row['voided_at'],
                'voidedBy': str(row['voided_by'] or ''),
                'voidedByName': row['voided_by_name'] or '',
                'voidReason': row['void_reason'],
                'createdAt': row['created_at'],
                'updatedAt': row['updated_at'],
            }
            for row in rows
        ],
    }


def _user_snapshots(restaurant, now):
    users = (
        User.objects.filter(restaurant_profile__restaurant=restaurant, is_active=True)
        .select_related('role', 'employee_profile', 'restaurant_profile', 'restaurant_profile__restaurant')
        .distinct()
    )
    snapshots = []
    for user in users:
        if not user.can_access_pos_ui:
            continue
        profile = user.restaurant_profile
        pin_hash = profile.pin_code or user.pin_code
        if not pin_hash:
            continue
        session = PosSessionSerializer({'token': '', 'user': user, 'restaurant': restaurant}).data
        snapshots.append(
            {
                'userId': str(user.id),
                'pinHash': pin_hash,
                'session': session,
                'rbacExpiresAt': (now + OFFLINE_RBAC_GRACE).isoformat(),
            }
        )
    return snapshots


def _device_bindings(restaurant):
    cash_desks = CashDesk.objects.filter(restaurant=restaurant, is_active=True).order_by('name')
    prep_stations = PrepStation.objects.filter(restaurant=restaurant, is_active=True).order_by('name')
    integrations = IntegrationConfig.objects.filter(restaurant=restaurant, is_enabled=True).order_by('kind', 'provider')
    return {
        'cashDesks': [
            {
                'id': str(item.id),
                'name': item.name,
                'location': item.location,
                'enabledPaymentMethods': item.enabled_payment_methods,
                'fiscalIntegrationId': str(item.fiscal_integration_id or ''),
                'paymentIntegrationId': str(item.payment_integration_id or ''),
                'printerIntegrationId': str(item.printer_integration_id or ''),
            }
            for item in cash_desks
        ],
        'prepStations': [
            {
                'id': str(item.id),
                'name': item.name,
                'kind': item.kind,
                'printerIntegrationId': str(item.printer_integration_id or ''),
            }
            for item in prep_stations
        ],
        'integrations': [
            {
                'id': str(item.id),
                'name': item.name,
                'kind': item.kind,
                'provider': item.provider,
                'settings': item.settings,
            }
            for item in integrations
        ],
    }


def _print_templates(restaurant):
    ensure_restaurant_templates(restaurant=restaurant)
    templates = PrintTemplate.objects.filter(restaurant=restaurant).select_related('published_version')
    return [
        {
            'id': str(template.id),
            'kind': template.kind,
            'name': template.get_kind_display(),
            'version': {
                'id': str(template.published_version_id),
                'revision': template.published_version.revision,
                'schemaVersion': template.published_version.schema_version,
                'layout': template.published_version.layout,
            },
        }
        for template in templates
        if template.published_version_id
    ]


class LocalAgentBootstrapView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LocalAgentRateThrottle]

    def get(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent token.'}, status=status.HTTP_401_UNAUTHORIZED)

        now = timezone.now()
        restaurant = agent.restaurant
        expenses = _expense_snapshot(restaurant)
        return Response(
            {
                'schemaVersion': 1,
                'serverCursor': now.isoformat(),
                'generatedAt': now.isoformat(),
                'restaurant': PosRestaurantContextSerializer(restaurant).data,
                'posDevices': pos_device_state_snapshot(restaurant=restaurant),
                'users': _user_snapshots(restaurant, now),
                'menu': _menu_snapshot(restaurant),
                'halls': _hall_snapshot(restaurant),
                'tableSessions': _table_session_snapshot(restaurant),
                'orders': _order_snapshot(restaurant, now),
                'kitchenTickets': _kitchen_snapshot(restaurant),
                'cashShifts': _cash_shift_snapshot(restaurant),
                'expenseCategories': expenses['categories'],
                'expenseRecipients': expenses['recipients'],
                'cashExpenses': expenses['expenses'],
                'bindings': _device_bindings(restaurant),
                'printTemplates': _print_templates(restaurant),
            }
        )


class LocalAgentPOSDeviceStateView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LocalAgentRateThrottle]

    def get(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent token.'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(
            {
                'schemaVersion': 1,
                'serverTime': timezone.now().isoformat(),
                'posDevices': pos_device_state_snapshot(restaurant=agent.restaurant),
            }
        )
