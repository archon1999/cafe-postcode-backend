import hashlib
import json
import re

from django.db.models import Sum
from rest_framework import status

from apps.billing.models import Payment
from apps.sales.models import Order


MUTATION_PATHS = (
    re.compile(r"^/api/v1/pos/sales/orders/$"),
    re.compile(r"^/api/v1/pos/sales/orders/[0-9a-f-]+/$"),
    re.compile(r"^/api/v1/pos/sales/orders/[0-9a-f-]+/items/$"),
    re.compile(r"^/api/v1/pos/sales/orders/[0-9a-f-]+/items/bulk/$"),
    re.compile(r"^/api/v1/pos/sales/orders/items/[0-9a-f-]+/$"),
    re.compile(r"^/api/v1/pos/sales/orders/[0-9a-f-]+/submit/$"),
    re.compile(r"^/api/v1/pos/sales/orders/[0-9a-f-]+/serve-ready/$"),
    re.compile(r"^/api/v1/pos/sales/orders/[0-9a-f-]+/scan-marking/$"),
    re.compile(r"^/api/v1/pos/floor/table-sessions/$"),
    re.compile(r"^/api/v1/pos/floor/table-sessions/[0-9a-f-]+/(?:move|merge|transfer|group|ungroup)/$"),
    re.compile(r"^/api/v1/pos/floor/tables/[0-9a-f-]+/reserve/$"),
    re.compile(r"^/api/v1/pos/billing/shifts/open/$"),
    re.compile(r"^/api/v1/pos/billing/shifts/current/close/$"),
    re.compile(r"^/api/v1/pos/billing/shifts/current/print-report/$"),
    re.compile(r"^/api/v1/pos/billing/shifts/current/expenses/$"),
    re.compile(r"^/api/v1/pos/billing/expenses/[0-9a-f-]+/void/$"),
    re.compile(r"^/api/v1/pos/billing/orders/[0-9a-f-]+/pay/$"),
    re.compile(r"^/api/v1/pos/billing/payments/[0-9a-f-]+/retry-fiscal/$"),
    re.compile(r"^/api/v1/pos/billing/payments/[0-9a-f-]+/print-document/$"),
    re.compile(r"^/api/v1/pos/billing/[0-9a-f-]+/refund/$"),
    re.compile(r"^/api/v1/pos/billing/fiscal-shifts/open/$"),
    re.compile(r"^/api/v1/pos/billing/fiscal-shifts/close/$"),
    re.compile(r"^/api/v1/pos/kitchen/tickets/[0-9a-f-]+/status/$"),
    re.compile(r"^/api/v1/pos/kitchen/items/[0-9a-f-]+/status/$"),
)
ALLOWED_METHODS = {"POST", "PATCH", "DELETE"}
ORDER_ITEM_DELETE_PATH = re.compile(r"^/api/v1/pos/sales/orders/items/[0-9a-f-]+/$")
ORDER_PAYMENT_PATH = re.compile(
    r"^/api/v1/pos/billing/orders/(?P<order_id>[0-9a-f-]+)/pay/$"
)


def reconciled_order_item_delete(*, method, path, response_status, response_body):
    if method != "DELETE" or not ORDER_ITEM_DELETE_PATH.fullmatch(path):
        return None
    if response_status == status.HTTP_404_NOT_FOUND:
        return {"reconciled": True, "reason": "already_absent"}
    detail = json.dumps(response_body or {}, ensure_ascii=False).lower()
    if (
        response_status == status.HTTP_400_BAD_REQUEST
        and "closed or cancelled orders cannot be modified" in detail
    ):
        return {"reconciled": True, "reason": "order_already_finalized"}
    return None


def reconciled_fully_paid_order(*, agent, method, path, response_status, response_body):
    match = ORDER_PAYMENT_PATH.fullmatch(path)
    if (
        method != "POST"
        or match is None
        or response_status != status.HTTP_400_BAD_REQUEST
    ):
        return None
    detail = json.dumps(response_body or {}, ensure_ascii=False).lower()
    if (
        "payment amount cannot exceed the remaining total" not in detail
        and "order is already fully paid" not in detail
    ):
        return None
    order = Order.objects.filter(
        id=match.group("order_id"),
        restaurant=agent.restaurant,
        status=Order.Status.CLOSED,
    ).first()
    if order is None:
        return None
    paid_total = (
        Payment.objects.filter(order=order, status=Payment.Status.SUCCEEDED)
        .aggregate(total=Sum("amount"))
        .get("total")
        or 0
    )
    if int(paid_total) < int(order.total or 0):
        return None
    return {
        "reconciled": True,
        "reason": "order_already_fully_paid",
        "orderId": str(order.id),
    }


def request_hash(*, user_id, method, path, body):
    canonical = json.dumps(
        {"userId": str(user_id), "method": method, "path": path, "body": body},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def allowed_mutation(method, path):
    return method in ALLOWED_METHODS and any(
        pattern.fullmatch(path) for pattern in MUTATION_PATHS
    )


def decode_response(response):
    if hasattr(response, "render") and not getattr(response, "is_rendered", True):
        response.render()
    content = bytes(getattr(response, "content", b"") or b"")
    if not content:
        return None
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return {"detail": content.decode("utf-8", errors="replace")}
