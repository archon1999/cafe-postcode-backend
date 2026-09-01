import json

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.local_agents.mutation_reconciliation import (
    allowed_mutation as _allowed_mutation,
    request_hash as _request_hash,
)
from common.api.throttling import LocalAgentRateThrottle


class LocalAgentMutationPushView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LocalAgentRateThrottle]
    request_factory_class = APIRequestFactory

    def post(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response(
                {"detail": "Invalid local agent token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        operations = (
            request.data.get("operations") if hasattr(request.data, "get") else None
        )
        if isinstance(operations, str):
            try:
                operations = json.loads(operations)
            except (TypeError, ValueError):
                operations = None
        if not isinstance(operations, list) or not operations or len(operations) > 100:
            return Response(
                {"operations": "Provide between 1 and 100 operations."}, status=400
            )

        processor = LocalAgentMutationProcessor(self.request_factory_class)
        return Response(
            {
                "results": [
                    processor.process(agent=agent, operation=operation)
                    for operation in operations
                ]
            }
        )
