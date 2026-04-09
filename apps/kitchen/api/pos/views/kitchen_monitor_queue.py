from datetime import timedelta

from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.api.pos.serializers.monitor_queue import KitchenMonitorQuerySerializer, KitchenMonitorQueueSerializer
from apps.kitchen.models import KitchenTicket
from apps.platform.services import FeatureGateService


class KitchenMonitorQueueView(APIView):
    permission_classes = [permissions.AllowAny]
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        serializer = KitchenMonitorQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        restaurant = serializer.validated_data['restaurant']
        self.feature_gate_service_class().ensure_kitchen_access(restaurant=restaurant)

        base_queryset = KitchenTicket.objects.filter(restaurant=restaurant).select_related('order').order_by('-created_at')
        preparing = base_queryset.filter(status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING)).order_by(
            'order__order_number',
            'created_at',
        )
        recent_done_cutoff = timezone.now() - timedelta(minutes=2)
        recently_done = base_queryset.filter(
            status=KitchenTicket.Status.DONE,
            completed_at__gte=recent_done_cutoff,
        ).order_by('-completed_at', '-created_at')

        return Response(
            KitchenMonitorQueueSerializer(
                {
                    'preparing': preparing,
                    'recently_done': recently_done,
                }
            ).data
        )
