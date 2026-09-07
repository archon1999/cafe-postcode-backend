"""Reconcile old global financial chains without changing original envelopes."""

from apps.local_agents.models import LocalAgentMutationInbox, LocalAgentMutationReceipt


FISCAL_PATHS = {
    "/pos/billing/fiscal-shifts/open/",
    "/pos/billing/fiscal-shifts/close/",
}


def normalized_path(operation):
    return str(operation.get("path") or "").removeprefix("/api/v1")


def unresolved_dependencies(inbox, dependencies):
    """Return real missing causes plus an auditable, versioned traversal.

    Only a stored earlier fiscal lifecycle event in this owner's epoch can be
    traversed. Its business ancestors still have to be applied. Missing events,
    conflicting epochs, forward references and cycles never grant a waiver.
    """
    root_path = normalized_path(inbox.operation)
    independent_business = (
        inbox.event_version == 2
        and bool(inbox.owner_epoch)
        and inbox.sequence is not None
        and root_path.startswith("/pos/billing/")
        and root_path not in FISCAL_PATHS
    )
    missing, decisions, visited = set(), [], {}
    pending = [(item, inbox.sequence) for item in dependencies]
    examined = 0
    while pending:
        operation_id, child_sequence = pending.pop()
        examined += 1
        if examined > 512:
            missing.add(operation_id)
            continue
        node = LocalAgentMutationInbox.objects.filter(
            restaurant_id=inbox.restaurant_id, operation_id=operation_id
        ).first()
        if node is not None and node.state in {"applied", "resolved"}:
            continue
        if LocalAgentMutationReceipt.objects.filter(
            restaurant_id=inbox.restaurant_id, operation_id=operation_id,
            response_status__gte=200, response_status__lt=300,
        ).exists():
            continue
        if not (
            independent_business
            and node is not None
            and node.event_version == 2
            and node.owner_epoch == inbox.owner_epoch
            and node.sequence is not None
            and child_sequence is not None
            and node.sequence < child_sequence
            and str(node.operation.get("method") or "").upper() == "POST"
            and normalized_path(node.operation) in FISCAL_PATHS
        ):
            missing.add(operation_id)
            continue
        if operation_id in visited:
            continue
        visited[operation_id] = True
        decisions.append({
            "rule": "independent_fiscal_lifecycle_v1",
            "operationId": operation_id,
            "payloadHash": node.payload_hash,
            "sequence": node.sequence,
            "path": node.operation["path"],
            "requiredAncestors": node.depends_on,
        })
        pending.extend((item, node.sequence) for item in node.depends_on)
    return sorted(missing), decisions
