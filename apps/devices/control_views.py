import logging

from django.conf import settings
from django.db.models import Count, Max, Q
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.control_serializers import (
    CONTROL_DEVICE_TYPES,
    ControlBranchSerializer,
    ControlDeviceRevokeSerializer,
    ControlDeviceSerializer,
    ControlPairingDecisionSerializer,
    ControlPairingRejectSerializer,
    ControlPairingResolveSerializer,
    ControlResolvedPairingSerializer,
    ControlTelegramSubscriptionSerializer,
)
from apps.devices.control_services import (
    CONTROL_PAIRING_MAX_FAILURES,
    ControlPairingAttemptsExceeded,
    ControlPairingInvalid,
    approve_control_pairing,
    record_control_pairing_failure,
    release_control_pairing_attempt,
    reject_control_pairing,
    reserve_control_pairing_attempt,
    resolve_control_pairing,
)
from apps.devices.models import Device
from apps.devices.permissions import IsControlOperator
from apps.devices.services import revoke_device
from apps.restaurants.models import Restaurant
from apps.telegram_reports.models import TelegramBranchSubscription, TelegramLinkToken
from apps.devices.security import record_security_event
from common.api.admin_permissions import RecentAdminMFAPermission
from common.api.permissions import EndpointRBACPermission
from common.api.throttling import ControlPairingDecisionRateThrottle, ControlPairingResolveRateThrottle


logger = logging.getLogger(__name__)


CONTROL_PERMISSIONS = [permissions.IsAuthenticated, EndpointRBACPermission, IsControlOperator]
CONTROL_SECURE_ACTION_PERMISSIONS = [*CONTROL_PERMISSIONS, RecentAdminMFAPermission]


def _control_restaurants(user):
    queryset = Restaurant.objects.all()
    if user.is_superuser:
        return queryset
    partner = user.get_business_partner_scope()
    if partner is None or partner.status != 'active':
        return queryset.none()
    return queryset.filter(business_partner_id=partner.id)


def _query_value(request, *names):
    for name in names:
        value = request.query_params.get(name)
        if value is not None:
            return str(value).strip()
    return ''


def _pairing_invalid_response(*, attempts_exceeded=False):
    return Response(
        {'code': 'pairing_invalid', 'detail': 'Pairing request is invalid.'},
        status=(status.HTTP_429_TOO_MANY_REQUESTS if attempts_exceeded else status.HTTP_400_BAD_REQUEST),
    )


def _record_pairing_failure(*, pairing_id, failure_count, request, restaurant=None):
    failure_count = record_control_pairing_failure(
        pairing_id=pairing_id,
        failure_count=failure_count,
        request=request,
        restaurant=restaurant,
    )
    return _pairing_invalid_response(attempts_exceeded=failure_count >= CONTROL_PAIRING_MAX_FAILURES)


class ControlBranchListView(generics.ListAPIView):
    permission_classes = CONTROL_PERMISSIONS
    serializer_class = ControlBranchSerializer

    def get_queryset(self):
        allowed_devices = Q(devices__type__in=CONTROL_DEVICE_TYPES, devices__restaurant__isnull=False)
        queryset = _control_restaurants(self.request.user).annotate(
            active_device_count=Count(
                'devices',
                filter=allowed_devices & Q(devices__status=Device.Status.ACTIVE),
                distinct=True,
            ),
            revoked_device_count=Count(
                'devices',
                filter=allowed_devices & Q(devices__status=Device.Status.REVOKED),
                distinct=True,
            ),
            last_seen_at=Max('devices__last_seen_at', filter=allowed_devices),
        )
        search = _query_value(self.request, 'search')[:200]
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(address__icontains=search))

        connection_status = _query_value(self.request, 'connection_status', 'connectionStatus')
        if connection_status == 'connected':
            queryset = queryset.filter(is_active=True, active_device_count__gt=0)
        elif connection_status == 'not_connected':
            queryset = queryset.filter(is_active=True, active_device_count=0)
        elif connection_status == 'inactive':
            queryset = queryset.filter(is_active=False)
        elif connection_status:
            queryset = queryset.none()

        ordering = _query_value(self.request, 'ordering')
        ordering_map = {
            'name': 'name',
            'address': 'address',
            'isActive': 'is_active',
            'is_active': 'is_active',
            'activeDeviceCount': 'active_device_count',
            'active_device_count': 'active_device_count',
            'revokedDeviceCount': 'revoked_device_count',
            'revoked_device_count': 'revoked_device_count',
            'lastSeenAt': 'last_seen_at',
            'last_seen_at': 'last_seen_at',
        }
        descending = ordering.startswith('-')
        requested_key = ordering[1:] if descending else ordering
        field = ordering_map.get(requested_key, 'name')
        return queryset.order_by(f'-{field}' if descending else field, 'id')


class ControlBranchDeviceListView(generics.ListAPIView):
    permission_classes = CONTROL_PERMISSIONS
    serializer_class = ControlDeviceSerializer

    def get_queryset(self):
        restaurant_id = self.kwargs['restaurant_id']
        if not _control_restaurants(self.request.user).filter(pk=restaurant_id).exists():
            return Device.objects.none()
        queryset = Device.objects.filter(
            restaurant_id=restaurant_id,
            type__in=CONTROL_DEVICE_TYPES,
        )
        ordering = _query_value(self.request, 'ordering')
        ordering_map = {
            'name': 'name',
            'type': 'type',
            'status': 'status',
            'lastSeenAt': 'last_seen_at',
            'last_seen_at': 'last_seen_at',
            'pairedAt': 'paired_at',
            'paired_at': 'paired_at',
        }
        descending = ordering.startswith('-')
        requested_key = ordering[1:] if descending else ordering
        field = ordering_map.get(requested_key, 'type')
        return queryset.order_by(f'-{field}' if descending else field, 'name', 'id')


class ControlPairingResolveView(APIView):
    permission_classes = CONTROL_PERMISSIONS
    throttle_classes = [ControlPairingResolveRateThrottle]

    def post(self, request):
        serializer = ControlPairingResolveSerializer(data=request.data)
        if not serializer.is_valid():
            return _pairing_invalid_response()
        pairing_id = serializer.validated_data['pairing_id']
        try:
            failure_count = reserve_control_pairing_attempt(pairing_id, phase='resolve')
            pairing = resolve_control_pairing(**serializer.validated_data)
        except ControlPairingAttemptsExceeded:
            return _pairing_invalid_response(attempts_exceeded=True)
        except ControlPairingInvalid:
            return _record_pairing_failure(
                pairing_id=pairing_id,
                failure_count=failure_count,
                request=request,
            )
        release_control_pairing_attempt(pairing_id, phase='resolve')
        return Response({'pairing': ControlResolvedPairingSerializer(pairing).data})


class _ControlPairingDecisionView(APIView):
    permission_classes = CONTROL_SECURE_ACTION_PERMISSIONS
    throttle_classes = [ControlPairingDecisionRateThrottle]
    serializer_class = None

    def get_restaurant(self, restaurant_id):
        return _control_restaurants(self.request.user).filter(pk=restaurant_id, is_active=True).first()

    def invalid_serializer_response(self, *, pairing_id, failure_count, request, restaurant):
        return _record_pairing_failure(
            pairing_id=pairing_id,
            failure_count=failure_count,
            request=request,
            restaurant=restaurant,
        )


class ControlPairingApproveView(_ControlPairingDecisionView):
    serializer_class = ControlPairingDecisionSerializer

    def post(self, request, restaurant_id, pairing_id):
        restaurant = self.get_restaurant(restaurant_id)
        try:
            failure_count = reserve_control_pairing_attempt(pairing_id, phase='decision')
        except ControlPairingAttemptsExceeded:
            return _pairing_invalid_response(attempts_exceeded=True)
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return self.invalid_serializer_response(
                pairing_id=pairing_id,
                failure_count=failure_count,
                request=request,
                restaurant=restaurant,
            )
        try:
            device = approve_control_pairing(
                pairing_id=pairing_id,
                restaurant=restaurant,
                approved_by=request.user,
                request=request,
                **serializer.validated_data,
            )
        except ControlPairingInvalid:
            return _record_pairing_failure(
                pairing_id=pairing_id,
                failure_count=failure_count,
                request=request,
                restaurant=restaurant,
            )
        return Response({'status': 'paired', 'device': ControlDeviceSerializer(device).data})


class ControlPairingRejectView(_ControlPairingDecisionView):
    serializer_class = ControlPairingRejectSerializer

    def post(self, request, restaurant_id, pairing_id):
        restaurant = self.get_restaurant(restaurant_id)
        try:
            failure_count = reserve_control_pairing_attempt(pairing_id, phase='decision')
        except ControlPairingAttemptsExceeded:
            return _pairing_invalid_response(attempts_exceeded=True)
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return self.invalid_serializer_response(
                pairing_id=pairing_id,
                failure_count=failure_count,
                request=request,
                restaurant=restaurant,
            )
        try:
            reject_control_pairing(
                pairing_id=pairing_id,
                restaurant=restaurant,
                rejected_by=request.user,
                request=request,
                **serializer.validated_data,
            )
        except ControlPairingInvalid:
            return _record_pairing_failure(
                pairing_id=pairing_id,
                failure_count=failure_count,
                request=request,
                restaurant=restaurant,
            )
        return Response({'status': 'rejected'})


class ControlDeviceRevokeView(APIView):
    permission_classes = CONTROL_SECURE_ACTION_PERMISSIONS

    def post(self, request, restaurant_id, device_id):
        device = Device.objects.filter(
            pk=device_id,
            restaurant_id=restaurant_id,
            restaurant__in=_control_restaurants(request.user),
            type__in=CONTROL_DEVICE_TYPES,
        ).first()
        if device is None:
            return Response(
                {'code': 'not_found', 'detail': 'Device was not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ControlDeviceRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = revoke_device(
            device=device,
            revoked_by=request.user,
            reason=serializer.validated_data['reason'],
            request=request,
        )
        return Response({'device': ControlDeviceSerializer(device).data})


class ControlTelegramSubscriptionListView(generics.ListAPIView):
    permission_classes = CONTROL_PERMISSIONS
    serializer_class = ControlTelegramSubscriptionSerializer

    def get_queryset(self):
        restaurant_id = self.kwargs['restaurant_id']
        if not _control_restaurants(self.request.user).filter(pk=restaurant_id).exists():
            return TelegramBranchSubscription.objects.none()
        return (
            TelegramBranchSubscription.objects.select_related('account')
            .filter(restaurant_id=restaurant_id)
            .order_by('account__username', 'account__telegram_user_id', 'id')
        )


class ControlTelegramLinkIssueView(APIView):
    permission_classes = CONTROL_SECURE_ACTION_PERMISSIONS

    def post(self, request, restaurant_id):
        restaurant = _control_restaurants(request.user).filter(pk=restaurant_id, is_active=True).first()
        if restaurant is None:
            return Response(
                {'code': 'not_found', 'detail': 'Restaurant was not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        bot_username = settings.TELEGRAM_REPORTS_BOT_USERNAME.lstrip('@').strip()
        if not bot_username:
            return Response(
                {'detail': 'Telegram reports bot username is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        token, raw_token = TelegramLinkToken.issue(
            restaurant=restaurant,
            issued_by=request.user,
            ttl_minutes=5,
        )
        logger.info(
            'Control Telegram link token issued',
            extra={
                'user_id': str(request.user.pk),
                'restaurant_id': str(restaurant.pk),
                'telegram_link_token_id': str(token.pk),
            },
        )
        record_security_event(
            event_type='TELEGRAM_LINK_TOKEN_ISSUED',
            severity='INFO',
            request=request,
            restaurant=restaurant,
            actor=request.user,
            result='SUCCESS',
            metadata={'linkArtifactId': str(token.pk), 'source': 'control'},
        )
        return Response(
            {
                'id': str(token.pk),
                'restaurantId': str(restaurant.pk),
                'restaurantName': restaurant.name,
                'startUrl': f'https://t.me/{bot_username}?start={raw_token}',
                'expiresAt': token.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )
