from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.api.pos.serializers.monitor_queue import KitchenMonitorQuerySerializer, KitchenMonitorQueueSerializer
from apps.kitchen.constants import KITCHEN_MONITOR_RECENTLY_DONE_WINDOW
from apps.kitchen.models import KitchenAnnouncement, KitchenTicket
from apps.kitchen.services import complete_stale_closed_order_kitchen_work
from apps.platform.services import FeatureGateService
from apps.sales.models import Order
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


def serialize_kitchen_monitor_queue(restaurant):
    complete_stale_closed_order_kitchen_work(restaurant=restaurant)
    base_queryset = KitchenTicket.objects.filter(restaurant=restaurant).select_related('order').order_by('-created_at')
    preparing_cutoff = timezone.now() - timedelta(days=1)
    active_order_statuses = [Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY]
    preparing = (
        base_queryset.filter(status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING))
        .filter(Q(order__status__in=active_order_statuses) | Q(created_at__gte=preparing_cutoff))
        .order_by('order__order_number', 'created_at')
    )
    recent_done_cutoff = timezone.now() - KITCHEN_MONITOR_RECENTLY_DONE_WINDOW
    recently_done = base_queryset.filter(
        status=KitchenTicket.Status.DONE,
        completed_at__gte=recent_done_cutoff,
    ).order_by('-completed_at', '-created_at')
    announcement_cutoff = timezone.now() - timedelta(minutes=10)
    announcements = KitchenAnnouncement.objects.filter(
        restaurant=restaurant,
        created_at__gte=announcement_cutoff,
    ).select_related('order').order_by('created_at')[:100]
    return KitchenMonitorQueueSerializer(
        {
            'monitor_variant': restaurant.pos_monitor_variant,
            'preparing': preparing,
            'recently_done': recently_done,
            'announcements': announcements,
        }
    ).data


class KitchenMonitorQueueView(APIView):
    permission_classes = [EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        serializer = KitchenMonitorQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        restaurant = get_request_restaurant(request)
        if serializer.validated_data['restaurant_id'] != restaurant.id:
            return Response({'detail': 'Restaurant does not match the authenticated user.'}, status=403)
        self.feature_gate_service_class().ensure_kitchen_access(restaurant=restaurant)
        return Response(serialize_kitchen_monitor_queue(restaurant))
