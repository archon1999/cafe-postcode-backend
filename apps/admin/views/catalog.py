from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import CatalogCategorySerializer, CatalogItemSerializer, MxikLookupResultSerializer
from apps.admin.support import CategoryListFilters, ItemListFilters, filter_catalog_queryset_by_scope
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.catalog.services.mxik import MxikClient, MxikError
from common.api.scopes import get_request_branch, get_request_restaurant


class CategoryListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = CatalogCategorySerializer
    permission_code = 'catalog.manage'

    def get_queryset(self):
        queryset = filter_catalog_queryset_by_scope(CatalogCategory.objects.all(), self.request)
        return CategoryListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant, branch=get_request_branch(self.request, restaurant))


class CategoryDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CatalogCategorySerializer
    permission_code = 'catalog.manage'

    def get_queryset(self):
        return filter_catalog_queryset_by_scope(CatalogCategory.objects.all(), self.request)


class ItemListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = CatalogItemSerializer
    permission_code = 'catalog.manage'

    def get_queryset(self):
        queryset = CatalogItem.objects.all().select_related('category', 'prep_station')
        queryset = filter_catalog_queryset_by_scope(queryset, self.request)
        return ItemListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant, branch=get_request_branch(self.request, restaurant))


class ItemDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CatalogItemSerializer
    permission_code = 'catalog.manage'

    def get_queryset(self):
        return filter_catalog_queryset_by_scope(CatalogItem.objects.all(), self.request).select_related(
            'category',
            'prep_station',
        )


class ItemStoplistToggleView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'catalog.manage'

    def post(self, request, pk):
        queryset = filter_catalog_queryset_by_scope(CatalogItem.objects.all(), request)
        item = generics.get_object_or_404(queryset, pk=pk)
        item.is_stoplisted = not item.is_stoplisted
        item.save(update_fields=['is_stoplisted', 'updated_at'])
        return Response(CatalogItemSerializer(item).data, status=status.HTTP_200_OK)


class MxikSearchView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'catalog.manage'

    def get(self, request):
        query = request.query_params.get('query', '').strip()
        if not query:
            return Response([], status=status.HTTP_200_OK)

        lang = request.query_params.get('lang', 'uz')
        limit = int(request.query_params.get('limit', 20) or 20)
        client = MxikClient()

        try:
            results = client.search_by_code(query, lang=lang, limit=limit) if query.isdigit() else client.search(
                query,
                lang=lang,
                limit=limit,
            )
        except MxikError as error:
            return Response({'detail': str(error)}, status=status.HTTP_502_BAD_GATEWAY)

        serializer = MxikLookupResultSerializer(results, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MxikLookupView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'catalog.manage'

    def get(self, request, code: str):
        lang = request.query_params.get('lang', 'uz')
        try:
            result = MxikClient().lookup(code, lang=lang)
        except MxikError as error:
            return Response({'detail': str(error)}, status=status.HTTP_404_NOT_FOUND)

        serializer = MxikLookupResultSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)
