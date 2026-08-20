from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.services import FakturaClient, FakturaError
from apps.platform.api.admin.permissions import NonRestaurantPermissionRequiredMixin
from apps.restaurants.api.admin.serializers import (
    RestaurantBranchCreateSerializer,
    RestaurantDetailSerializer,
    RestaurantListSerializer,
    RestaurantLookupSerializer,
    RestaurantPortfolioSummarySerializer,
    RestaurantSerializer,
)
from apps.restaurants.selectors.restaurants import (
    RestaurantListFilters,
    get_restaurant_portfolio_summary,
    get_restaurants_queryset_for_request,
    with_restaurant_detail_annotations,
    with_restaurant_list_annotations,
)
from common.api.admin_permissions import AdminPermissionRequiredMixin


class RestaurantListCreateView(NonRestaurantPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = RestaurantSerializer

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return RestaurantListSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        scoped_queryset = get_restaurants_queryset_for_request(self.request)
        queryset = with_restaurant_list_annotations(
            scoped_queryset.defer(
                'currency',
                'faktura_payload',
                'last_order_number',
                'marking_check_enabled',
                'payment_total_mode',
                'pos_auth_background_image',
                'pos_monitor_variant',
                'service_fee_enabled',
                'service_fee_percent',
                'social',
                'vat_enabled',
                'vat_percent',
            ),
            branch_queryset=scoped_queryset,
        )
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


class RestaurantBranchCreateView(NonRestaurantPermissionRequiredMixin, generics.CreateAPIView):
    serializer_class = RestaurantBranchCreateSerializer

    def get_parent_restaurant(self):
        return get_object_or_404(
            get_restaurants_queryset_for_request(self.request),
            pk=self.kwargs['pk'],
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['parent_restaurant'] = self.get_parent_restaurant()
        return context

    def perform_create(self, serializer):
        parent = self.get_parent_restaurant()
        serializer.save(
            parent_restaurant=parent,
            business_partner=parent.business_partner,
        )


class RestaurantDetailView(NonRestaurantPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RestaurantSerializer

    def get_queryset(self):
        return get_restaurants_queryset_for_request(self.request)


class RestaurantReadDetailView(NonRestaurantPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = RestaurantDetailSerializer

    def get_queryset(self):
        scoped_queryset = get_restaurants_queryset_for_request(self.request)
        return with_restaurant_detail_annotations(
            scoped_queryset,
            branch_queryset=scoped_queryset,
        )


class RestaurantPortfolioSummaryView(NonRestaurantPermissionRequiredMixin, APIView):
    def get(self, request):
        queryset = get_restaurants_queryset_for_request(request)
        queryset = RestaurantListFilters.from_request(request).apply(
            queryset,
            with_ordering=False,
        )
        summary = get_restaurant_portfolio_summary(queryset)
        return Response(RestaurantPortfolioSummarySerializer(summary).data)

__all__ = [
    'RestaurantBranchCreateView',
    'RestaurantDetailView',
    'RestaurantListCreateView',
    'RestaurantLookupView',
    'RestaurantPortfolioSummaryView',
    'RestaurantReadDetailView',
]
