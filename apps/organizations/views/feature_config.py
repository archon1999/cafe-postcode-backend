from rest_framework import generics, permissions

from apps.organizations.models import FeatureConfig
from apps.organizations.serializers import FeatureConfigSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class FeatureConfigView(generics.RetrieveUpdateAPIView):
    serializer_class = FeatureConfigSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_object(self):
        restaurant = get_request_restaurant(self.request)
        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=restaurant)
        return feature_config
