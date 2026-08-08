from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.api.pos.serializers import KitchenAnnouncementSerializer
from apps.kitchen.models import KitchenTicket
from apps.kitchen.services import create_replay_announcement
from apps.platform.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class KitchenTicketAnnouncementView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        ticket = generics.get_object_or_404(
            KitchenTicket.objects.select_related('order'),
            pk=pk,
            restaurant=restaurant,
        )
        self.feature_gate_service_class().ensure_kitchen_access(restaurant=restaurant, interactive=True)

        if ticket.status != KitchenTicket.Status.DONE:
            raise serializers.ValidationError({'detail': 'Only ready kitchen orders can be announced.'})
        if ticket.order.kitchen_tickets.exclude(status=KitchenTicket.Status.DONE).exists():
            raise serializers.ValidationError({'detail': 'The whole order must be ready before it can be announced.'})

        announcement = create_replay_announcement(ticket=ticket, user=request.user)
        return Response(KitchenAnnouncementSerializer(announcement).data, status=status.HTTP_201_CREATED)
