from rest_framework import serializers

from apps.integrations.models import IntegrationConfig
from apps.restaurants.selectors.restaurants import (
    get_restaurants_queryset_for_request,
    with_restaurant_list_annotations,
)
from apps.restaurants.services.setup import restaurant_setup_readiness
from apps.users.helpers import get_employee_profile_model, get_user_model
from common.utils.settings import get_setting

from .restaurant import RestaurantSerializer
from .restaurant_overview import (
    RestaurantBranchSummarySerializer,
    RestaurantOperationalSummarySerializer,
    RestaurantSetupReadinessSummarySerializer,
)

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


class RestaurantDetailSerializer(RestaurantSerializer):
    active_users = serializers.SerializerMethodField()
    soliq_integration = serializers.SerializerMethodField()
    operational_summary = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()
    setup_readiness = serializers.SerializerMethodField()

    class Meta(RestaurantSerializer.Meta):
        fields = RestaurantSerializer.Meta.fields + (
            "active_users",
            "soliq_integration",
            "operational_summary",
            "branches",
            "setup_readiness",
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

    def get_operational_summary(self, instance):
        payload = {
            "active_users": getattr(instance, "active_users_count", 0),
            "cash_desks": getattr(instance, "active_cash_desks_count", 0),
            "prep_stations": getattr(instance, "active_prep_stations_count", 0),
            "distribution_points": getattr(
                instance,
                "active_distribution_points_count",
                0,
            ),
            "menu_items": getattr(instance, "active_menu_items_count", 0),
            "active_devices": getattr(instance, "active_device_count", 0),
            "online_devices": getattr(instance, "online_device_count", 0),
            "last_seen_at": getattr(instance, "last_seen_at", None),
        }
        return RestaurantOperationalSummarySerializer(payload).data

    def get_branches(self, instance):
        request = self.context.get("request")
        if request is not None:
            scoped_queryset = get_restaurants_queryset_for_request(request)
        else:
            scoped_queryset = instance.branches.model.objects.filter(
                business_partner_id=instance.business_partner_id
            )
        queryset = with_restaurant_list_annotations(
            scoped_queryset.filter(parent_restaurant_id=instance.pk),
            branch_queryset=scoped_queryset,
        ).order_by("name")
        return RestaurantBranchSummarySerializer(queryset, many=True).data

    def get_setup_readiness(self, instance):
        readiness = restaurant_setup_readiness(restaurant=instance)
        steps = []
        for step in readiness.get("steps", []):
            issues = list(step.get("issues", []))
            steps.append(
                {
                    "id": step.get("id", ""),
                    "status": step.get("status", ""),
                    "issue_count": len(issues),
                    "blocking_issue_count": sum(
                        1 for issue in issues if issue.get("blocking")
                    ),
                    "issue_codes": [
                        str(issue.get("code", ""))
                        for issue in issues
                        if issue.get("code")
                    ],
                }
            )
        payload = {
            "ready": bool(readiness.get("ready")),
            "progress_percent": int(readiness.get("progressPercent", 0)),
            "blocking_issue_count": int(
                readiness.get("blockingIssueCount", 0)
            ),
            "steps": steps,
        }
        return RestaurantSetupReadinessSummarySerializer(payload).data
