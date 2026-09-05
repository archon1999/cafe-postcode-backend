from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.models import LocalAgentCommand, LocalAgentMutationInbox
from common.api.scopes import get_request_restaurant


class FinancialCommandStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, operation_id):
        restaurant = get_request_restaurant(request)
        user_id = str(request.user.pk)
        inbox = LocalAgentMutationInbox.objects.filter(
            restaurant=restaurant, operation_id=operation_id
        ).first()
        if (
            inbox is not None
            and str(inbox.operation.get("userId") or inbox.operation.get("user_id"))
            == user_id
        ):
            applied = inbox.state == "applied"
            result = inbox.last_result or {}
            return Response(
                {
                    "commandId": operation_id,
                    "state": "succeeded" if applied else "unknown",
                    "stage": inbox.state,
                    "responseStatus": result.get("status"),
                    "response": result.get("body"),
                    "payloadSha256": inbox.payload_hash,
                    "durablyReceived": True,
                    "applied": applied,
                    "retryAllowed": False,
                    "manualConfirmationAllowed": False,
                }
            )
        command = LocalAgentCommand.objects.filter(
            agent__restaurant=restaurant, financial_operation_id=operation_id
        ).first()
        if command is None or str(command.payload.get("actorUserId") or command.payload.get("userId")) != user_id:
            return Response(
                {
                    "code": "FINANCIAL_COMMAND_NOT_FOUND",
                    "commandId": operation_id,
                    "state": "unknown",
                    "retryAllowed": False,
                },
                status=404,
            )
        result = command.result or {}
        complete = command.status == LocalAgentCommand.Status.SUCCEEDED
        response_status = int(result.get("responseStatus") or 200) if complete else None
        response = result.get("response", result) if complete else None
        owner = (
            (
                response.get("financialCommand")
                or response.get("financial_command")
                or {}
            )
            if isinstance(response, dict)
            else {}
        )
        owner_state = owner.get("state")
        state = "unknown"
        if complete and owner_state in {"unknown", "processing", "failed", "succeeded"}:
            state = owner_state
        elif complete and response_status < 400:
            state = "succeeded"
        return Response(
            {
                "commandId": operation_id,
                "state": state,
                "stage": command.status,
                "responseStatus": response_status,
                "response": response,
                "payloadSha256": command.payload_hash,
                "retryAllowed": False,
                "manualConfirmationAllowed": False,
            }
        )
