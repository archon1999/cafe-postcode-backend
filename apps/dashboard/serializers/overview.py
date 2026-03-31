from rest_framework import serializers


class DashboardContextSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class DashboardRestaurantSerializer(DashboardContextSerializer):
    currency = serializers.CharField()


class DashboardTopItemSerializer(serializers.Serializer):
    item_name = serializers.CharField(allow_null=True)
    quantity = serializers.IntegerField()
    revenue = serializers.IntegerField()


class DashboardStaffBreakdownSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(allow_null=True)
    user_name = serializers.CharField(allow_null=True)
    orders_count = serializers.IntegerField()
    sales_total = serializers.IntegerField()


class DashboardOverviewSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    restaurant = DashboardRestaurantSerializer()
    sales_total = serializers.IntegerField()
    orders_count = serializers.IntegerField()
    average_check = serializers.IntegerField()
    top_items = DashboardTopItemSerializer(many=True)
    waiter_breakdown = DashboardStaffBreakdownSerializer(many=True)
    cashier_breakdown = DashboardStaffBreakdownSerializer(many=True)
