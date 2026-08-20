from rest_framework import serializers

from apps.restaurants.helpers import get_restaurant_model

from .restaurant_mixins import RestaurantEntitlementFieldsMixin

Restaurant = get_restaurant_model()


class RestaurantListSerializer(
    RestaurantEntitlementFieldsMixin,
    serializers.ModelSerializer,
):
    parent_id = serializers.UUIDField(
        source='parent_restaurant_id',
        read_only=True,
        allow_null=True,
    )
    parent_name = serializers.CharField(
        source='parent_restaurant.name',
        read_only=True,
        allow_null=True,
    )
    branch_type = serializers.SerializerMethodField()
    branch_count = serializers.IntegerField(read_only=True)
    active_users_count = serializers.IntegerField(read_only=True)
    active_device_count = serializers.IntegerField(read_only=True)
    online_device_count = serializers.IntegerField(read_only=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Restaurant
        fields = (
            'id',
            'parent_id',
            'parent_name',
            'branch_type',
            'name',
            'legal_name',
            'tax_number',
            'phone',
            'address',
            'is_active',
            'restaurant_access_active',
            'activation_type',
            'activated_at',
            'deactivated_at',
            'tariff',
            'branch_count',
            'active_users_count',
            'active_device_count',
            'online_device_count',
            'last_seen_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    @staticmethod
    def get_branch_type(instance):
        return 'branch' if instance.parent_restaurant_id else 'root'


class RestaurantBranchSummarySerializer(serializers.ModelSerializer):
    restaurant_access_active = serializers.SerializerMethodField()
    active_users_count = serializers.IntegerField(read_only=True)
    active_device_count = serializers.IntegerField(read_only=True)
    online_device_count = serializers.IntegerField(read_only=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Restaurant
        fields = (
            'id',
            'name',
            'address',
            'is_active',
            'restaurant_access_active',
            'active_users_count',
            'active_device_count',
            'online_device_count',
            'last_seen_at',
        )
        read_only_fields = fields

    @staticmethod
    def get_restaurant_access_active(instance):
        entitlement = getattr(instance, 'entitlement', None)
        return bool(entitlement and entitlement.is_active)


class RestaurantOperationalSummarySerializer(serializers.Serializer):
    active_users = serializers.IntegerField(read_only=True)
    cash_desks = serializers.IntegerField(read_only=True)
    prep_stations = serializers.IntegerField(read_only=True)
    distribution_points = serializers.IntegerField(read_only=True)
    menu_items = serializers.IntegerField(read_only=True)
    active_devices = serializers.IntegerField(read_only=True)
    online_devices = serializers.IntegerField(read_only=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)


class RestaurantSetupReadinessStepSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    issue_count = serializers.IntegerField(read_only=True)
    blocking_issue_count = serializers.IntegerField(read_only=True)
    issue_codes = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class RestaurantSetupReadinessSummarySerializer(serializers.Serializer):
    ready = serializers.BooleanField(read_only=True)
    progress_percent = serializers.IntegerField(read_only=True)
    blocking_issue_count = serializers.IntegerField(read_only=True)
    steps = RestaurantSetupReadinessStepSerializer(many=True, read_only=True)


class RestaurantPortfolioSummarySerializer(serializers.Serializer):
    total_count = serializers.IntegerField(read_only=True)
    root_count = serializers.IntegerField(read_only=True)
    branch_count = serializers.IntegerField(read_only=True)
    active_count = serializers.IntegerField(read_only=True)
    inactive_count = serializers.IntegerField(read_only=True)
    draft_count = serializers.IntegerField(read_only=True)
    access_mismatch_count = serializers.IntegerField(read_only=True)
    without_tariff_count = serializers.IntegerField(read_only=True)
    active_users_count = serializers.IntegerField(read_only=True)
    active_device_count = serializers.IntegerField(read_only=True)
    online_device_count = serializers.IntegerField(read_only=True)


__all__ = [
    'RestaurantBranchSummarySerializer',
    'RestaurantListSerializer',
    'RestaurantOperationalSummarySerializer',
    'RestaurantPortfolioSummarySerializer',
    'RestaurantSetupReadinessStepSerializer',
    'RestaurantSetupReadinessSummarySerializer',
]
