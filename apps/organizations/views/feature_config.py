from rest_framework import generics, permissions

from apps.organizations.models import FeatureConfig
from apps.organizations.serializers import FeatureConfigSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class FeatureConfigView(generics.RetrieveUpdateAPIView):
    serializer_class = FeatureConfigSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_object(self):
        restaurant = get_request_restaurant(self.request)
        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=restaurant)
        return feature_config
