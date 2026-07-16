from rest_framework import serializers

from apps.integrations.models import IntegrationConfig
from apps.platform.services import get_restaurant_balance_summary
from apps.users.helpers import get_employee_profile_model, get_user_model
from common.utils.settings import get_setting

from .restaurant import RestaurantSerializer

EmployeeProfile = get_employee_profile_model()
User = get_user_model()


class RestaurantActiveUserRoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField(allow_blank=True, allow_null=True)
    name = serializers.CharField()


class RestaurantActiveUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "full_name", "username", "role")

    def get_role(self, instance):
        if instance.role is None:
            return None
        return RestaurantActiveUserRoleSerializer(instance.role).data


class RestaurantSoliqIntegrationSerializer(serializers.Serializer):
    configured = serializers.BooleanField()
    is_enabled = serializers.BooleanField()
    provider = serializers.CharField()
    terminal_id = serializers.CharField(allow_null=True)
    cashbox_id = serializers.CharField(allow_null=True)
    tax_number = serializers.CharField(allow_null=True)
    endpoint_url = serializers.CharField(allow_null=True)


class RestaurantBalanceSummarySerializer(serializers.Serializer):
    current_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    next_charge_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    next_charge_on = serializers.DateField(allow_null=True)
    next_period_status = serializers.ChoiceField(
        choices=("active", "inactive"), allow_null=True
    )
    last_top_up_at = serializers.DateTimeField(allow_null=True)


class RestaurantDetailSerializer(RestaurantSerializer):
    active_users = serializers.SerializerMethodField()
    soliq_integration = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta(RestaurantSerializer.Meta):
        fields = RestaurantSerializer.Meta.fields + (
            "active_users",
            "soliq_integration",
            "balance",
        )

    def get_active_users(self, instance):
        active_users = (
            User.objects.filter(restaurant_profile__restaurant=instance, is_active=True)
            .select_related("role", "employee_profile")
            .exclude(
                employee_profile__employment_status__in=(
                    EmployeeProfile.EmploymentStatus.INACTIVE,
                    EmployeeProfile.EmploymentStatus.ARCHIVED,
                )
            )
            .order_by("full_name", "username")
            .distinct()
        )
        return RestaurantActiveUserSerializer(active_users, many=True).data

    def get_soliq_integration(self, instance):
        config = (
            IntegrationConfig.objects.filter(
                restaurant=instance, kind=IntegrationConfig.Kind.FISCAL
            )
            .order_by("-is_enabled", "provider", "-created_at")
            .first()
        )
        if config is None:
            return None

        payload = {
            "configured": True,
            "is_enabled": config.is_enabled,
            "provider": config.provider,
            "terminal_id": get_setting(config.settings, "terminal_id", "terminalId"),
            "cashbox_id": get_setting(config.settings, "cashbox_id", "cashboxId"),
            "tax_number": get_setting(config.settings, "tax_number", "taxNumber"),
            "endpoint_url": get_setting(config.settings, "endpoint_url", "endpointUrl"),
        }
        return RestaurantSoliqIntegrationSerializer(payload).data

    def get_balance(self, instance):
        return RestaurantBalanceSummarySerializer(
            get_restaurant_balance_summary(instance)
        ).data
