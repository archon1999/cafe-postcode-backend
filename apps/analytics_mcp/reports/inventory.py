"""Read-only inventory evidence for ChatGPT. Ledger mutations are intentionally unavailable."""

from decimal import Decimal

from pydantic import Field

from apps.inventory import reports as inventory_reports
from apps.inventory.models import Recipe, StockBalance, StockDocument, StockDocumentLine
from ..contracts import BranchInput, PeriodInput
from ..registry import ReportDefinition


class InventoryListInput(BranchInput):
    limit: int = Field(default=20, ge=1, le=50)


class InventoryPeriodInput(PeriodInput):
    limit: int = Field(default=20, ge=1, le=50)


def branch_field(context, restaurant_id):
    return {"branch_id": str(restaurant_id)} if len(context.branches) > 1 else {}


def inventory_summary(context, params):
    balances = []
    for branch in context.branches:
        balances.extend((branch.pk, row) for row in inventory_reports.balances(branch))
    low_rows = []
    negative_count = 0
    low_count = 0
    for restaurant_id, balance in balances:
        quantity = Decimal(balance["quantity"])
        negative = quantity < 0
        low = balance["is_low"]
        negative_count += int(negative)
        low_count += int(low)
        if (negative or low) and len(low_rows) < params.limit:
            low_rows.append({
                **branch_field(context, restaurant_id),
                "warehouse_id": balance["warehouse"],
                "warehouse": balance["warehouse_name"],
                "item_id": balance["item"],
                "item": balance["item_name"],
                "item_kind": balance["item_kind"],
                "quantity": quantity,
                "unit": balance["base_unit"],
                "minimum": Decimal(balance["min_quantity"]),
                "negative": negative,
            })
    context.warnings.append(
        "Balances are ledger projections. Physical shortage is confirmed only by a posted stocktake."
    )
    return {
        "balance_rows": len(balances),
        "low_stock_count": low_count,
        "negative_stock_count": negative_count,
        "alerts": low_rows,
        "limit": params.limit,
    }


def inventory_variance(context, params):
    rows = StockDocumentLine.objects.filter(
        document__restaurant__in=context.branches,
        document__kind=StockDocument.Kind.STOCKTAKE,
        document__status="posted",
        document__occurred_at__gte=context.period.start,
        document__occurred_at__lt=context.period.end,
    ).select_related("document__restaurant", "document__warehouse", "item")
    result = []
    for line in rows.order_by("-document__occurred_at", "item__name")[: params.limit]:
        denominator = line.consumption_quantity
        percent = abs(line.variance_quantity) / denominator * 100 if denominator else None
        result.append({
            **branch_field(context, line.document.restaurant_id),
            "document": line.document.number,
            "occurred_at": line.document.occurred_at.isoformat(),
            "warehouse": line.document.warehouse.name,
            "item": line.item_name,
            "unit": line.base_unit,
            "expected": line.expected_quantity,
            "actual": line.base_quantity,
            "variance": line.variance_quantity,
            "variance_percent": percent,
            "tolerance_percent": line.tolerance_percent,
        })
    context.warnings.append(
        "Variance percent uses theoretical recipe consumption since the previous count; without consumption it is null."
    )
    return {"variances": result, "row_count": rows.count(), "limit": params.limit}


def production_yield(context, params):
    documents = StockDocument.objects.filter(
        restaurant__in=context.branches,
        kind=StockDocument.Kind.PRODUCTION,
        status="posted",
        occurred_at__gte=context.period.start,
        occurred_at__lt=context.period.end,
    ).select_related("restaurant", "warehouse", "production_recipe__output_item")
    rows = []
    for document in documents.order_by("-occurred_at")[: params.limit]:
        planned = document.planned_quantity or Decimal("0")
        actual = document.actual_quantity or Decimal("0")
        rows.append({
            **branch_field(context, document.restaurant_id),
            "document": document.number,
            "occurred_at": document.occurred_at.isoformat(),
            "warehouse": document.warehouse.name,
            "output": document.production_recipe.output_item.name,
            "planned": planned,
            "actual": actual,
            "yield_percent": actual / planned * 100 if planned else None,
        })
    return {"batches": rows, "batch_count": documents.count(), "limit": params.limit}


def recipe_costs(context, params):
    recipes = Recipe.objects.filter(
        restaurant__in=context.branches, is_active=True
    ).select_related("restaurant", "catalog_item", "output_item").prefetch_related("lines__item")
    balances = StockBalance.objects.filter(
        warehouse__restaurant__in=context.branches, warehouse__is_default=True
    ).values("warehouse__restaurant_id", "item_id", "average_cost")
    costs = {
        (row["warehouse__restaurant_id"], str(row["item_id"])): row["average_cost"]
        for row in balances
    }
    rows = []
    for recipe in recipes.order_by("restaurant_id", "catalog_item__name", "output_item__name")[: params.limit]:
        from apps.inventory.services import components_for

        components = components_for(recipe, Decimal("1"), set())
        cost = sum(
            (
                quantity * costs.get((recipe.restaurant_id, item_id), Decimal("0"))
                for item_id, quantity in components.items()
            ),
            Decimal("0"),
        )
        sale_price = recipe.catalog_item.price if recipe.catalog_item_id else None
        rows.append({
            **branch_field(context, recipe.restaurant_id),
            "recipe_id": str(recipe.pk),
            "target_type": "catalog" if recipe.catalog_item_id else "preparation",
            "name": recipe.catalog_item.name if recipe.catalog_item_id else recipe.output_item.name,
            "version": recipe.version,
            "estimated_unit_cost": cost,
            "sale_price": sale_price,
            "gross_margin": Decimal(sale_price) - cost if sale_price is not None else None,
        })
    context.warnings.append(
        "Recipe cost uses current weighted-average ingredient costs in each branch's default warehouse; it is an estimate, not a posted accounting valuation."
    )
    return {"recipes": rows, "recipe_count": recipes.count(), "limit": params.limit}


def purchase_recommendations(context, params):
    rows = []
    for branch in context.branches:
        facts = inventory_reports.insights(branch).get("items", [])
        for fact in facts:
            if fact.get("id", "").startswith(("negative:", "low:", "runway:")):
                rows.append({
                    **branch_field(context, branch.pk),
                    "evidence_id": fact["id"],
                    "severity": fact["severity"],
                    "title": fact["title"],
                    "detail": fact["detail"],
                    "recommendation": fact["recommendation"],
                    "evidence": fact["evidence"],
                })
                if len(rows) >= params.limit:
                    break
        if len(rows) >= params.limit:
            break
    context.warnings.append(
        "Recommendations are deterministic operational alerts. Supplier lead time, delivery schedule and safety stock are not yet modeled."
    )
    return {"recommendations": rows, "limit": params.limit}


REPORTS = (
    ReportDefinition(
        "get_inventory_summary",
        "Ombor qoldiqlari",
        "Read current low and negative stock across authorized branches and warehouses.",
        InventoryListInput,
        inventory_summary,
        permission="admin.inventory.view",
        requires_single_currency=False,
        metric_basis={"balance": "posted immutable StockMovement projection"},
    ),
    ReportDefinition(
        "get_inventory_variance",
        "Inventarizatsiya farqi",
        "Read physical-count variances and theoretical-consumption percentages for a period.",
        InventoryPeriodInput,
        inventory_variance,
        permission="admin.inventory.view",
        requires_single_currency=False,
        metric_basis={"variance": "posted stocktake actual minus captured expected balance"},
    ),
    ReportDefinition(
        "get_production_yield",
        "Ishlab chiqarish chiqishi",
        "Read planned versus actual semi-finished production batches and yield percentages.",
        InventoryPeriodInput,
        production_yield,
        permission="admin.inventory.view",
        requires_single_currency=False,
        metric_basis={"yield": "posted production actual output / planned output"},
    ),
    ReportDefinition(
        "get_recipe_costs",
        "Retsept tannarxi",
        "Read current estimated recipe costs and gross margin using default-warehouse average costs.",
        InventoryListInput,
        recipe_costs,
        permission="admin.inventory.view_cost",
        metric_basis={"cost": "active recipe quantities at current weighted-average ingredient cost"},
    ),
    ReportDefinition(
        "get_purchase_recommendations",
        "Xarid tavsiyalari",
        "Read evidence-grounded low-stock and estimated depletion alerts for purchase planning.",
        InventoryListInput,
        purchase_recommendations,
        permission="admin.inventory.view",
        requires_single_currency=False,
        metric_basis={"recommendation": "current balance, minimum stock and recent recipe depletion"},
    ),
)
