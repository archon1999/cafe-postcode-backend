"""Reconcile old global financial chains without changing original envelopes."""

import re

from apps.local_agents.models import LocalAgentMutationInbox, LocalAgentMutationReceipt


FISCAL_PATHS = {
    "/pos/billing/fiscal-shifts/open/",
    "/pos/billing/fiscal-shifts/close/",
}


def normalized_path(operation):
    return str(operation.get("path") or "").removeprefix("/api/v1")


def payment_order(operation):
    if str(operation.get("method") or "").upper() != "POST":
        return None
    match = re.fullmatch(r"/pos/billing/orders/([0-9a-f-]+)/pay/", normalized_path(operation))
    return match[1] if match else None


def unresolved_dependencies(inbox, dependencies):
    """Return real missing causes plus an auditable, versioned traversal.

    Stored earlier fiscal events, or another order's payment for a payment root,
    can be traversed in the same owner's epoch. Same-order and cash lifecycle,
    refund and expense ancestors remain required. Missing events,
    conflicting epochs, forward references and cycles never grant a waiver.
    """
    root_path = normalized_path(inbox.operation)
    root_order = payment_order(inbox.operation)
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
        if examined > 8192:
            missing.add(operation_id)
            continue
        node = LocalAgentMutationInbox.objects.filter(
            restaurant_id=inbox.restaurant_id, operation_id=operation_id
        ).first()
        prior_owner_event = (
            independent_business and node is not None
            and node.event_version == 2 and node.owner_epoch == inbox.owner_epoch
            and node.sequence is not None and child_sequence is not None
            and node.sequence < child_sequence
        )
        # An applied payment on B may have legitimately bypassed failed A.
        # Its original chain is still needed by a later A payment or cash-close
        # barrier. An applied acknowledgment alone is not transitive proof.
        traverse_applied_payment = (
            prior_owner_event and payment_order(node.operation)
            and node.state == "applied"
        )
        if traverse_applied_payment:
            if operation_id not in visited:
                visited[operation_id] = True
                # A versioned certificate produced by this policy contains the
                # remaining unpaid ancestry. Avoid walking every settled sale
                # in the shift again for every subsequent payment (O(n^2)).
                ancestors = node.depends_on
                if node.last_result.get("dependencyPolicy") == "order_isolation_v1":
                    certified = node.last_result.get("deferredOrderDependencies")
                    if isinstance(certified, list) and all(isinstance(item, str) for item in certified):
                        ancestors = certified
                decisions.append({
                    "rule": "applied_order_payment_ancestry_v1",
                    "operationId": operation_id, "payloadHash": node.payload_hash,
                    "sequence": node.sequence, "path": node.operation["path"],
                    "requiredAncestors": ancestors,
                })
                pending.extend((item, node.sequence) for item in ancestors)
            continue
        if node is not None and node.state in {"applied", "resolved"}:
            continue
        if LocalAgentMutationReceipt.objects.filter(
            restaurant_id=inbox.restaurant_id, operation_id=operation_id,
            response_status__gte=200, response_status__lt=300,
        ).exists():
            continue
        if not (
            prior_owner_event
            and str(node.operation.get("method") or "").upper() == "POST"
            and (
                normalized_path(node.operation) in FISCAL_PATHS
                or (root_order and payment_order(node.operation)
                    and payment_order(node.operation) != root_order)
            )
        ):
            missing.add(operation_id)
            continue
        if operation_id in visited:
            continue
        visited[operation_id] = True
        decisions.append({
            "rule": ("independent_order_payment_v1" if payment_order(node.operation)
                     else "independent_fiscal_lifecycle_v1"),
            "operationId": operation_id,
            "payloadHash": node.payload_hash,
            "sequence": node.sequence,
            "path": node.operation["path"],
            "requiredAncestors": node.depends_on,
        })
        pending.extend((item, node.sequence) for item in node.depends_on)
    return sorted(missing), decisions
