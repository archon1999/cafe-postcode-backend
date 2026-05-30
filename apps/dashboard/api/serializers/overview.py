from rest_framework import serializers


class DashboardRestaurantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    currency = serializers.CharField()
    address = serializers.CharField(allow_blank=True)


class DashboardPeriodSerializer(serializers.Serializer):
    period_type = serializers.CharField()
    value = serializers.CharField()
    label = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    comparison_value = serializers.CharField()
    comparison_label = serializers.CharField()
    comparison_start_date = serializers.DateField()
    comparison_end_date = serializers.DateField()
    chart_granularity = serializers.CharField()


class DashboardSummarySerializer(serializers.Serializer):
    sales_total = serializers.IntegerField()
    orders_count = serializers.IntegerField()
    average_check = serializers.IntegerField()
    open_checks = serializers.IntegerField()
    active_tables = serializers.IntegerField()


class DashboardSummaryDeltaSerializer(serializers.Serializer):
    sales_total = serializers.FloatField()
    orders_count = serializers.FloatField()
    average_check = serializers.FloatField()
    open_checks = serializers.FloatField()
    active_tables = serializers.FloatField()


class DashboardTopItemSerializer(serializers.Serializer):
    catalog_item_id = serializers.UUIDField(allow_null=True, required=False)
    item_name = serializers.CharField(allow_null=True)
    category_id = serializers.UUIDField(allow_null=True, required=False)
    category_name = serializers.CharField(allow_null=True, required=False)
    quantity = serializers.IntegerField()
    revenue = serializers.IntegerField()


class DashboardStaffSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(allow_null=True)
    user_name = serializers.CharField(allow_null=True)
    orders_count = serializers.IntegerField()
    items_count = serializers.IntegerField()
    sales_total = serializers.IntegerField()
    average_check = serializers.IntegerField(required=False)


class DashboardBreakdownSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    orders_count = serializers.IntegerField()
    sales_total = serializers.IntegerField()
    share = serializers.IntegerField()


class DashboardRevenueSeriesPointSerializer(serializers.Serializer):
    bucket_index = serializers.IntegerField()
    label = serializers.CharField()
    sales_total = serializers.IntegerField()
    orders_count = serializers.IntegerField()
    average_check = serializers.IntegerField()


class DashboardPeakTimeBucketSerializer(serializers.Serializer):
    bucket_index = serializers.IntegerField()
    label = serializers.CharField()
    sales_total = serializers.IntegerField()
    orders_count = serializers.IntegerField()


class DashboardSpotlightSerializer(serializers.Serializer):
    top_item = DashboardTopItemSerializer(allow_null=True)
    top_waiter = DashboardStaffSerializer(allow_null=True)
    top_cashier = DashboardStaffSerializer(allow_null=True)
    top_manager = DashboardStaffSerializer(allow_null=True)
    top_channel = DashboardBreakdownSerializer(allow_null=True)
    top_payment_method = DashboardBreakdownSerializer(allow_null=True)
    peak_time_bucket = DashboardPeakTimeBucketSerializer()


class DashboardStaffBreakdownGroupSerializer(serializers.Serializer):
    waiters = DashboardStaffSerializer(many=True)
    cashiers = DashboardStaffSerializer(many=True)
    managers = DashboardStaffSerializer(many=True)


class DashboardOpenCheckSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.IntegerField()
    status = serializers.CharField()
    total = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    hall_id = serializers.UUIDField(allow_null=True)
    hall_name = serializers.CharField(allow_null=True)
    table_name = serializers.CharField(allow_null=True)


class DashboardOpenChecksSnapshotSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    active_tables = serializers.IntegerField()
    rows = DashboardOpenCheckSerializer(many=True)


class DashboardCashShiftSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    opened_at = serializers.DateTimeField()
    closed_at = serializers.DateTimeField(allow_null=True)
    opening_cash_amount = serializers.IntegerField()
    actual_closing_cash_amount = serializers.IntegerField()
    expected_closing_cash_amount = serializers.IntegerField()
    cash_difference_amount = serializers.IntegerField()
    cash_total = serializers.IntegerField()
    card_total = serializers.IntegerField()
    qr_total = serializers.IntegerField()
    refund_total = serializers.IntegerField()
    receipt_count = serializers.IntegerField()
    reprint_count = serializers.IntegerField()
    cash_desk_id = serializers.UUIDField(allow_null=True)
    cash_desk_name = serializers.CharField(allow_null=True)
    cashier_id = serializers.UUIDField(allow_null=True)
    cashier_name = serializers.CharField(allow_null=True)
    gross_total = serializers.IntegerField()
    is_difference = serializers.BooleanField()


class DashboardCashShiftSnapshotSerializer(serializers.Serializer):
    open_count = serializers.IntegerField()
    difference_count = serializers.IntegerField()
    cash_total = serializers.IntegerField()
    card_total = serializers.IntegerField()
    qr_total = serializers.IntegerField()
    refund_total = serializers.IntegerField()
    receipt_count = serializers.IntegerField()
    rows = DashboardCashShiftSerializer(many=True)


class DashboardOverviewSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    restaurant = DashboardRestaurantSerializer()
    period = DashboardPeriodSerializer()
    summary = DashboardSummarySerializer()
    summary_delta = DashboardSummaryDeltaSerializer()
    spotlight = DashboardSpotlightSerializer()
    revenue_series = DashboardRevenueSeriesPointSerializer(many=True)
    previous_revenue_series = DashboardRevenueSeriesPointSerializer(many=True)
    top_items = DashboardTopItemSerializer(many=True)
    staff_breakdown = DashboardStaffBreakdownGroupSerializer()
    payment_method_breakdown = DashboardBreakdownSerializer(many=True)
    channel_breakdown = DashboardBreakdownSerializer(many=True)
    open_checks_snapshot = DashboardOpenChecksSnapshotSerializer()
    cash_shift_snapshot = DashboardCashShiftSnapshotSerializer()
