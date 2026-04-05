from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.serializers import MxikLookupResultSerializer
from apps.catalog.services.mxik import MxikClient, MxikError
from common.api.permissions import EndpointRBACPermission


class MxikSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

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


class MxikLookupView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request, code: str):
        lang = request.query_params.get('lang', 'uz')
        try:
            result = MxikClient().lookup(code, lang=lang)
        except MxikError as error:
            return Response({'detail': str(error)}, status=status.HTTP_404_NOT_FOUND)

        serializer = MxikLookupResultSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)


__all__ = ['MxikLookupView', 'MxikSearchView']
