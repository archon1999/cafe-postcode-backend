from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.services import FakturaClient, FakturaError
from apps.restaurants.api.admin.serializers import RestaurantLookupSerializer, RestaurantSerializer
from apps.restaurants.selectors.restaurants import RestaurantListFilters, get_restaurants_queryset_for_request
from common.api.admin_permissions import AdminPermissionRequiredMixin


class RestaurantListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = RestaurantSerializer

    def get_queryset(self):
        queryset = get_restaurants_queryset_for_request(self.request)
        return RestaurantListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        business_partner = self.request.user.get_business_partner_scope()
        serializer.save(business_partner=business_partner)


class RestaurantLookupView(AdminPermissionRequiredMixin, APIView):
    def get(self, request):
        tax_number = (
            request.query_params.get('taxNumber')
            or request.query_params.get('tax_number')
            or ''
        ).strip()
        if not tax_number:
            raise serializers.ValidationError({'taxNumber': 'Tax number is required.'})

        try:
            faktura_payload = FakturaClient().lookup_company_basic_details(tax_number)
        except FakturaError as error:
            return Response({'detail': str(error)}, status=status.HTTP_502_BAD_GATEWAY)

        company_name = str(faktura_payload.get('CompanyName') or '').strip()
        payload = {
            'taxNumber': str(faktura_payload.get('CompanyInn') or tax_number).strip(),
            'name': company_name,
            'legal_name': company_name,
            'phone': str(faktura_payload.get('PhoneNumber') or '').strip(),
            'address': str(faktura_payload.get('CompanyAddress') or '').strip(),
            'faktura_payload': faktura_payload,
        }
        return Response(RestaurantLookupSerializer(payload).data, status=status.HTTP_200_OK)


class RestaurantDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RestaurantSerializer

    def get_queryset(self):
        return get_restaurants_queryset_for_request(self.request)

__all__ = ['RestaurantDetailView', 'RestaurantListCreateView', 'RestaurantLookupView']
