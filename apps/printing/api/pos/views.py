from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.services import LocalAgentCommandService, LocalAgentUnavailableError
from apps.printing.models import PrintDocument
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PosPrintJobSerializer(serializers.Serializer):
    operation_id = serializers.RegexField(r'^[a-zA-Z0-9._:-]{8,128}$')
    document_id = serializers.UUIDField()
    copies = serializers.IntegerField(required=False, default=1, min_value=1, max_value=5)


class PosPrintJobCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    command_service_class = LocalAgentCommandService

    def post(self, request):
        serializer = PosPrintJobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = get_request_restaurant(request)
        document = PrintDocument.objects.filter(
            id=serializer.validated_data['document_id'], restaurant=restaurant
        ).first()
        if document is None:
            return Response({'detail': 'Print document was not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            result = self.command_service_class().enqueue(
                restaurant=restaurant,
                command_type='print.document',
                payload={
                    'operationId': serializer.validated_data['operation_id'],
                    'documentId': str(document.id),
                    'copies': serializer.validated_data['copies'],
                },
                timeout_seconds=100,
            )
        except LocalAgentUnavailableError as error:
            return Response({'detail': str(error), 'code': error.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {
                'ok': True,
                'job': {
                    'operationId': serializer.validated_data['operation_id'],
                    'documentId': str(document.id),
                    'copies': serializer.validated_data['copies'],
                    'status': 'queued',
                    'commandId': result['commandId'],
                },
            },
            status=status.HTTP_202_ACCEPTED,
        )
