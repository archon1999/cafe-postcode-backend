from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.printing.api.admin.serializers import (
    PrintTemplateSerializer,
    PrintTemplateVersionCreateSerializer,
    PrintTemplateVersionSerializer,
)
from apps.printing.models import PrintTemplate, PrintTemplateVersion
from apps.printing.presets import (
    PRINT_KINDS,
    VARIABLE_GROUPS,
    VARIABLES_BY_KIND,
    get_preset_catalog,
    get_sample_data,
)
from apps.printing.services import create_template_version, ensure_restaurant_templates, publish_template_version
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class RestaurantPrintTemplateQuerysetMixin:
    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        ensure_restaurant_templates(restaurant=restaurant)
        return (
            PrintTemplate.objects.filter(restaurant=restaurant, kind__in=PRINT_KINDS)
            .select_related('published_version')
            .prefetch_related('versions')
        )


class PrintTemplateListView(RestaurantPrintTemplateQuerysetMixin, generics.ListAPIView):
    serializer_class = PrintTemplateSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    pagination_class = None


class PrintTemplateDetailView(RestaurantPrintTemplateQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = PrintTemplateSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]


class PrintTemplateVersionCreateView(RestaurantPrintTemplateQuerysetMixin, generics.GenericAPIView):
    serializer_class = PrintTemplateVersionCreateSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def post(self, request, pk):
        template = self.get_object()
        serializer = self.get_serializer(data=request.data, context={'request': request, 'template': template})
        serializer.is_valid(raise_exception=True)
        version = create_template_version(
            template=template,
            layout=serializer.validated_data.get('layout'),
            preset_key=serializer.validated_data.get('preset_key', ''),
            created_by=request.user,
        )
        return Response(PrintTemplateVersionSerializer(version).data, status=status.HTTP_201_CREATED)


class PrintTemplateVersionPublishView(RestaurantPrintTemplateQuerysetMixin, APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def post(self, request, pk, version_pk):
        restaurant = get_request_restaurant(request)
        template = generics.get_object_or_404(PrintTemplate, pk=pk, restaurant=restaurant)
        version = generics.get_object_or_404(PrintTemplateVersion, pk=version_pk, template=template)
        published = publish_template_version(template=template, version=version)
        return Response(PrintTemplateVersionSerializer(published).data)


class PrintPresetCatalogView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request):
        return Response(
            {
                'presets': get_preset_catalog(),
                'variableGroups': VARIABLE_GROUPS,
                'variablesByKind': VARIABLES_BY_KIND,
                'sampleData': get_sample_data(),
            }
        )
