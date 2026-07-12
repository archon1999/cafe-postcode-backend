from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.restaurants.api.admin.serializers import RestaurantSetupApplySerializer
from apps.restaurants.services.setup import apply_restaurant_setup, restaurant_setup_readiness
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant


class RestaurantSetupReadinessView(AdminPermissionRequiredMixin, APIView):
    def get(self, request):
        restaurant = get_request_restaurant(request)
        backend_url = request.build_absolute_uri('/').rstrip('/')
        return Response(restaurant_setup_readiness(restaurant=restaurant, backend_url=backend_url))


class RestaurantSetupApplyView(AdminPermissionRequiredMixin, APIView):
    def post(self, request):
        serializer = RestaurantSetupApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = get_request_restaurant(request)
        result = apply_restaurant_setup(restaurant=restaurant, payload=serializer.validated_data)
        backend_url = request.build_absolute_uri('/').rstrip('/')
        return Response(
            {
                'result': result,
                'readiness': restaurant_setup_readiness(restaurant=restaurant, backend_url=backend_url),
            },
            status=status.HTTP_200_OK,
        )
