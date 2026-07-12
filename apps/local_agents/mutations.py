import hashlib
import json
import re

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.urls import Resolver404, resolve
from djangorestframework_camel_case.util import camelize
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.billing.models import CashShift
from apps.billing.serializers import CashierContextSerializer
from apps.billing.services import CashShiftService
from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.models import LocalAgentMutationReceipt
from apps.kitchen.models import KitchenTicket
from apps.users.models import User


MUTATION_PATHS = (
    re.compile(r'^/api/v1/pos/sales/orders/$'),
    re.compile(r'^/api/v1/pos/sales/orders/[0-9a-f-]+/$'),
    re.compile(r'^/api/v1/pos/sales/orders/[0-9a-f-]+/items/$'),
    re.compile(r'^/api/v1/pos/sales/orders/items/[0-9a-f-]+/$'),
    re.compile(r'^/api/v1/pos/sales/orders/[0-9a-f-]+/submit/$'),
    re.compile(r'^/api/v1/pos/sales/orders/[0-9a-f-]+/scan-marking/$'),
    re.compile(r'^/api/v1/pos/floor/table-sessions/$'),
    re.compile(r'^/api/v1/pos/floor/tables/[0-9a-f-]+/reserve/$'),
    re.compile(r'^/api/v1/pos/billing/shifts/open/$'),
    re.compile(r'^/api/v1/pos/billing/shifts/current/close/$'),
    re.compile(r'^/api/v1/pos/billing/orders/[0-9a-f-]+/pay/$'),
    re.compile(r'^/api/v1/pos/billing/payments/[0-9a-f-]+/retry-fiscal/$'),
    re.compile(r'^/api/v1/pos/billing/payments/[0-9a-f-]+/print-document/$'),
    re.compile(r'^/api/v1/pos/billing/[0-9a-f-]+/refund/$'),
    re.compile(r'^/api/v1/pos/billing/fiscal-shifts/open/$'),
    re.compile(r'^/api/v1/pos/billing/fiscal-shifts/close/$'),
    re.compile(r'^/api/v1/pos/kitchen/tickets/[0-9a-f-]+/status/$'),
    re.compile(r'^/api/v1/pos/kitchen/items/[0-9a-f-]+/status/$'),
)
ALLOWED_METHODS = {'POST', 'PATCH', 'DELETE'}


def _request_hash(*, user_id, method, path, body):
    canonical = json.dumps(
        {'userId': str(user_id), 'method': method, 'path': path, 'body': body},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _allowed_mutation(method, path):
    return method in ALLOWED_METHODS and any(pattern.fullmatch(path) for pattern in MUTATION_PATHS)


def _decode_response(response):
    if hasattr(response, 'render') and not getattr(response, 'is_rendered', True):
        response.render()
    content = bytes(getattr(response, 'content', b'') or b'')
    if not content:
        return None
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return {'detail': content.decode('utf-8', errors='replace')}


class LocalAgentMutationPushView(APIView):
    permission_classes = [permissions.AllowAny]
    request_factory_class = APIRequestFactory

    def post(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent token.'}, status=status.HTTP_401_UNAUTHORIZED)

        operations = request.data.get('operations') if hasattr(request.data, 'get') else None
        if isinstance(operations, str):
            try:
                operations = json.loads(operations)
            except (TypeError, ValueError):
                operations = None
        if not isinstance(operations, list) or not operations or len(operations) > 100:
            return Response({'operations': 'Provide between 1 and 100 operations.'}, status=400)

        results = [self._process_operation(agent=agent, operation=operation) for operation in operations]
        return Response({'results': results})

    def _process_operation(self, *, agent, operation):
        if not isinstance(operation, dict):
            return {'ok': False, 'status': 400, 'error': 'Operation must be an object.', 'retryable': False}

        operation_id = str(operation.get('operationId') or operation.get('operation_id') or '').strip()
        user_id = str(operation.get('userId') or operation.get('user_id') or '').strip()
        method = str(operation.get('method') or '').strip().upper()
        path = str(operation.get('path') or '').strip()
        body = operation.get('body') if isinstance(operation.get('body'), dict) else {}
        if not operation_id or len(operation_id) > 128:
            return {'operationId': operation_id, 'ok': False, 'status': 400, 'error': 'Invalid operationId.', 'retryable': False}
        if not _allowed_mutation(method, path):
            return {'operationId': operation_id, 'ok': False, 'status': 403, 'error': 'Mutation path is not allowed.', 'retryable': False}

        digest = _request_hash(user_id=user_id, method=method, path=path, body=body)
        existing = LocalAgentMutationReceipt.objects.filter(operation_id=operation_id).first()
        if existing is not None:
            if existing.restaurant_id != agent.restaurant_id or existing.request_hash != digest:
                return {
                    'operationId': operation_id,
                    'ok': False,
                    'status': 409,
                    'error': 'operationId already belongs to another mutation.',
                    'retryable': False,
                }
            recoverable_shift_conflict = (
                path == '/api/v1/pos/billing/shifts/open/'
                and existing.response_status == status.HTTP_400_BAD_REQUEST
                and 'already has an active shift' in json.dumps(existing.response_body).lower()
            )
            if recoverable_shift_conflict:
                existing.delete()
            else:
                return {
                    'operationId': operation_id,
                    'ok': 200 <= existing.response_status < 300,
                    'status': existing.response_status,
                    'body': existing.response_body,
                    'replayed': True,
                    'retryable': False,
                }

        user = (
            User.objects.filter(id=user_id, restaurant_profile__restaurant=agent.restaurant, is_active=True)
            .select_related('role', 'restaurant_profile', 'employee_profile')
            .first()
        )
        if user is None or not user.can_access_pos_ui:
            return {'operationId': operation_id, 'ok': False, 'status': 403, 'error': 'POS user is invalid.', 'retryable': False}

        if path == '/api/v1/pos/billing/shifts/open/':
            reconciled = self._reconcile_open_shift(
                agent=agent,
                user=user,
                operation_id=operation_id,
                method=method,
                path=path,
                digest=digest,
                body=body,
            )
            if reconciled is not None:
                return reconciled

        dispatch_path = path
        if path == '/api/v1/pos/billing/shifts/current/close/':
            edge_cashier_id = body.pop('edgeCashierId', body.pop('edge_cashier_id', None))
            edge_cash_desk_id = body.pop('edgeCashDeskId', body.pop('edge_cash_desk_id', None))
            if edge_cashier_id and edge_cash_desk_id:
                shift = (
                    CashShift.objects.filter(
                        cash_desk__restaurant=agent.restaurant,
                        cash_desk_id=edge_cash_desk_id,
                        status=CashShift.Status.OPEN,
                    )
                    .filter(Q(cashier_id=edge_cashier_id) | Q(opened_by_id=edge_cashier_id))
                    .order_by('opened_at')
                    .first()
                )
                if shift is None:
                    return {
                        'operationId': operation_id,
                        'ok': False,
                        'status': 409,
                        'error': 'Cashier shift is not synchronized yet.',
                        'retryable': True,
                    }
                body['cashShiftId'] = str(shift.id)
        if re.fullmatch(r'/api/v1/pos/kitchen/tickets/[0-9a-f-]+/status/', path):
            edge_order_id = body.pop('edgeOrderId', body.pop('edge_order_id', None))
            prep_station_id = body.pop('prepStationId', body.pop('prep_station_id', None))
            if edge_order_id and prep_station_id:
                ticket = KitchenTicket.objects.filter(
                    restaurant=agent.restaurant,
                    order_id=edge_order_id,
                    prep_station_id=prep_station_id,
                ).first()
                if ticket is None:
                    return {
                        'operationId': operation_id,
                        'ok': False,
                        'status': 409,
                        'error': 'Kitchen ticket is not synchronized yet.',
                        'retryable': True,
                    }
                dispatch_path = f'/api/v1/pos/kitchen/tickets/{ticket.id}/status/'

        try:
            match = resolve(dispatch_path)
        except Resolver404:
            return {'operationId': operation_id, 'ok': False, 'status': 404, 'error': 'Mutation endpoint was not found.', 'retryable': False}

        factory = self.request_factory_class()
        internal_request = factory.generic(
            method,
            dispatch_path,
            data=json.dumps(body),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
            HTTP_X_EDGE_OPERATION_ID=operation_id,
        )
        # This server-side marker cannot be supplied by an external HTTP client.
        # Payment replay uses it to accept an already completed local terminal charge
        # without asking MARTA to charge the card a second time.
        internal_request.trusted_edge_replay = True
        internal_request.resolver_match = match
        force_authenticate(internal_request, user=user)
        response = match.func(internal_request, *match.args, **match.kwargs)
        response_body = _decode_response(response)
        response_status = int(response.status_code)

        if response_status < 500:
            LocalAgentMutationReceipt.objects.create(
                restaurant=agent.restaurant,
                operation_id=operation_id,
                user_id=user.id,
                method=method,
                path=path,
                request_hash=digest,
                response_status=response_status,
                response_body=response_body if response_body is not None else {},
            )
        return {
            'operationId': operation_id,
            'ok': 200 <= response_status < 300,
            'status': response_status,
            'body': response_body,
            'replayed': False,
            'retryable': response_status >= 500,
        }

    @staticmethod
    def _reconcile_open_shift(*, agent, user, operation_id, method, path, digest, body):
        cash_desk_id = body.get('cashDeskId') or body.get('cash_desk_id')
        requested_cashier_id = str(body.get('cashierId') or body.get('cashier_id') or user.id)
        shifts = CashShift.objects.filter(
            cash_desk__restaurant=agent.restaurant,
            status=CashShift.Status.OPEN,
        ).select_related('cash_desk', 'cashier', 'opened_by')
        if cash_desk_id:
            shifts = shifts.filter(cash_desk_id=cash_desk_id)

        matching = [
            shift
            for shift in shifts
            if str(shift.cashier_id or shift.opened_by_id) == requested_cashier_id
        ]
        if len(matching) != 1:
            return None

        response_body = camelize(json.loads(
            json.dumps(
                CashierContextSerializer(
                    CashShiftService().build_context(restaurant=agent.restaurant, user=user)
                ).data,
                cls=DjangoJSONEncoder,
            )
        ))
        response_status = status.HTTP_200_OK
        LocalAgentMutationReceipt.objects.create(
            restaurant=agent.restaurant,
            operation_id=operation_id,
            user_id=user.id,
            method=method,
            path=path,
            request_hash=digest,
            response_status=response_status,
            response_body=response_body,
        )
        return {
            'operationId': operation_id,
            'ok': True,
            'status': response_status,
            'body': response_body,
            'replayed': False,
            'reconciled': True,
            'retryable': False,
        }
