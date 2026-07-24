from apps.reporting.services import ReportPeriod


class OwnerDashboardRowsMixin:
    def build_expense_rows(self, restaurant, period: ReportPeriod, *, limit: int = 5) -> list[dict]:
        queryset = (
            self.get_expense_queryset(restaurant, period)
            .select_related('cash_desk', 'created_by')
            .order_by('-occurred_at', '-created_at')[:limit]
        )
        return [
            {
                'id': row.id,
                'amount': int(row.amount or 0),
                'category_name': row.category_name_snapshot,
                'comment': row.comment,
                'recipient_name': row.recipient_name_snapshot,
                'created_by_name': row.created_by.full_name if row.created_by_id else '',
                'cash_desk_name': row.cash_desk.name,
                'occurred_at': row.occurred_at,
            }
            for row in queryset
        ]

    def get_role_breakdown_rows(
        self, restaurant, period: ReportPeriod, *, role: str
    ) -> list[dict]:
        if role == "cashier":
            queryset = self.get_cashier_queryset(restaurant, period)
        elif role == "manager":
            queryset = self.get_manager_queryset(restaurant, period)
        else:
            queryset = self.get_waiter_queryset(restaurant, period)
        rows = []
        for row in queryset:
            orders_count = self.get_safe_number(row.get("orders_count"))
            sales_total = self.get_safe_number(row.get("sales_total"))
            items_count = self.get_safe_number(row.get("items_count"))
            rows.append(
                {
                    "user_id": row.get("user_id"),
                    "user_name": row.get("user_name"),
                    "orders_count": orders_count,
                    "items_count": items_count,
                    "sales_total": sales_total,
                    "average_check": round(sales_total / orders_count)
                    if orders_count
                    else 0,
                }
            )
        return rows

    @staticmethod
    def get_safe_number(value) -> int:
        return int(value or 0)

    def build_choice_breakdown(
        self, rows: list[dict], choices, *, total_sales: int
    ) -> list[dict]:
        rows_by_code = {
            (row.get("code") or row.get("method")): row
            for row in rows
            if row.get("code") or row.get("method")
        }
        breakdown = []
        for code, label in choices:
            row = rows_by_code.get(code, {})
            sales_total = self.get_safe_number(
                row.get("sales_total") or row.get("total")
            )
            orders_count = self.get_safe_number(
                row.get("orders_count") or row.get("count")
            )
            share = round((sales_total / total_sales) * 100) if total_sales > 0 else 0
            breakdown.append(
                {
                    "code": code,
                    "label": label,
                    "orders_count": orders_count,
                    "sales_total": sales_total,
                    "share": share,
                }
            )
        return breakdown

    def build_summary_delta(
        self, current_summary: dict, previous_summary: dict
    ) -> dict:
        return {
            key: self.get_change_pct(
                current_summary.get(key, 0), previous_summary.get(key, 0)
            )
            for key in (
                "sales_total",
                "orders_count",
                "average_check",
                "open_checks",
                "active_tables",
                "expenses_total",
                "expenses_count",
            )
        }

    def get_change_pct(self, current_value: int, previous_value: int) -> float:
        if not previous_value:
            return 100.0 if current_value > 0 else 0.0
        return round(((current_value - previous_value) / previous_value) * 100, 2)

    def build_top_items(
        self, restaurant, period: ReportPeriod, *, limit: int | None = None
    ) -> list[dict]:
        queryset = self.get_top_items_queryset(restaurant, period)
        if limit:
            queryset = queryset[:limit]
        rows = []
        for row in queryset:
            rows.append(
                {
                    "catalog_item_id": row.get("catalog_item_id"),
                    "item_name": row.get("catalog_item_name"),
                    "category_id": row.get("category_id"),
                    "category_name": row.get("category_name"),
                    "quantity": self.get_safe_number(row.get("quantity")),
                    "revenue": self.get_safe_number(row.get("revenue")),
                }
            )
        return rows

    def build_open_checks_rows(
        self, restaurant, period: ReportPeriod, *, limit: int | None = None
    ) -> list[dict]:
        queryset = self.get_open_checks_queryset(restaurant, period)
        if limit:
            queryset = queryset[:limit]
        return [
            {
                "id": row["id"],
                "order_number": row["order_number"],
                "status": row["status"],
                "total": self.get_safe_number(row.get("total")),
                "created_at": row["created_at"],
                "hall_id": row.get("hall_id"),
                "hall_name": row.get("hall_name"),
                "table_name": row.get("table_name"),
            }
            for row in queryset
        ]

    def build_shift_rows(
        self, restaurant, period: ReportPeriod, *, limit: int | None = None
    ) -> list[dict]:
        queryset = self.get_shift_queryset(restaurant, period)
        if limit:
            queryset = queryset[:limit]
        rows = []
        for row in queryset:
            cash_total = self.get_safe_number(row.get("cash_total"))
            card_total = self.get_safe_number(row.get("card_total"))
            qr_total = self.get_safe_number(row.get("qr_total"))
            rows.append(
                {
                    "id": row["id"],
                    "status": row["status"],
                    "opened_at": row["opened_at"],
                    "closed_at": row.get("closed_at"),
                    "opening_cash_amount": self.get_safe_number(
                        row.get("opening_cash_amount")
                    ),
                    "actual_closing_cash_amount": self.get_safe_number(
                        row.get("actual_closing_cash_amount")
                    ),
                    "expected_closing_cash_amount": self.get_safe_number(
                        row.get("expected_closing_cash_amount")
                    ),
                    "cash_difference_amount": self.get_safe_number(
                        row.get("cash_difference_amount")
                    ),
                    "cash_total": cash_total,
                    "card_total": card_total,
                    "qr_total": qr_total,
                    "refund_total": self.get_safe_number(row.get("refund_total")),
                    "expense_total": self.get_safe_number(row.get("expense_total")),
                    "receipt_count": self.get_safe_number(row.get("receipt_count")),
                    "reprint_count": self.get_safe_number(row.get("reprint_count")),
                    "cash_desk_id": row.get("cash_desk_id"),
                    "cash_desk_name": row.get("cash_desk_name"),
                    "cashier_id": row.get("cashier_id") or row.get("opened_by_id"),
                    "cashier_name": row.get("cashier_name"),
                    "gross_total": cash_total + card_total + qr_total,
                    "is_difference": bool(
                        self.get_safe_number(row.get("cash_difference_amount"))
                    ),
                }
            )
        return rows
