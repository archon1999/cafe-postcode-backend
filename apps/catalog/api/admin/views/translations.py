import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.catalog.serializers.name_translation import CatalogNameTranslationSerializer
from apps.catalog.services.name_translation import (
    CatalogNameTranslationConfigurationError,
    CatalogNameTranslationError,
    translate_catalog_name,
)
from common.api.permissions import EndpointRBACPermission

logger = logging.getLogger(__name__)


class CatalogNameTranslationView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "catalog_translation"

    def post(self, request):
        serializer = CatalogNameTranslationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            translated = translate_catalog_name(serializer.validated_data)
        except CatalogNameTranslationConfigurationError:
            logger.exception("Yandex Translate integration is not configured.")
            return Response(
                {
                    "code": "catalog_translation_not_configured",
                    "detail": "Tarjima xizmati sozlanmagan.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except CatalogNameTranslationError:
            logger.exception("Catalog name translation failed.")
            return Response(
                {
                    "code": "catalog_translation_failed",
                    "detail": "Nomni avtomatik tarjima qilib bo‘lmadi.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(translated.as_dict(), status=status.HTTP_200_OK)
