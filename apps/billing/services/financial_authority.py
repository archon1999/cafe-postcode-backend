from rest_framework.exceptions import APIException


class FinancialAgentRequired(APIException):
    status_code = 409
    default_code = "FINANCIAL_AGENT_REQUIRED"
    default_detail = (
        "Complete this financial operation through the assigned Local Agent."
    )

    def __init__(self):
        super().__init__({"code": self.default_code, "detail": self.default_detail})


def dispatch_to_financial_owner(
    *, request, restaurant, fallback_operation_id=None, path=None, execution_user=None
):
    """Compatibility adapter; execute committed command outside DB transactions.

    The owner journals and executes the same path as a local POS, then replicates
    resulting evidence. A cloud request never executes a raw fiscal-device RPC.
    """
    from rest_framework.response import Response
    from apps.local_agents.models import LocalAgent
    from apps.local_agents.services import (
        LocalAgentCommandService,
        LocalAgentCommandError,
        LocalAgentUnavailableError,
    )

    agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).first()
    if agent is None or "financial_events_v2" not in (agent.capabilities or []):
        return Response(
            {
                "code": "FINANCIAL_OWNER_UPGRADE_REQUIRED",
                "detail": "Update the assigned Local Agent to financial events v2 before using this operation.",
            },
            status=409,
        )
    operation_id = str(
        request.headers.get("X-Edge-Operation-ID")
        or request.data.get("edge_operation_id")
        or request.data.get("edgeOperationId")
        or fallback_operation_id
        or ""
    ).strip()
    if not operation_id or len(operation_id) > 128:
        return Response(
            {
                "code": "FINANCIAL_COMMAND_ID_REQUIRED",
                "detail": "Use a stable operation ID through the assigned Local Agent.",
            },
            status=409,
        )
    try:
        result = LocalAgentCommandService().execute(
            restaurant=restaurant,
            command_type="financial.execute",
            timeout_seconds=45,
            payload={
                "operationId": operation_id,
                "userId": str((execution_user or request.user).pk),
                **({"actorUserId": str(request.user.pk)} if execution_user else {}),
                "method": request.method,
                "path": path or request.path,
                "body": dict(request.data),
            },
        )
    except (LocalAgentCommandError, LocalAgentUnavailableError) as error:
        return Response(
            {
                "code": error.code,
                "commandId": operation_id,
                "state": "unknown",
                "detail": str(error),
                "retryAllowed": False,
            },
            status=409,
        )
    return Response(
        result.get("response", result), status=int(result.get("responseStatus") or 200)
    )
