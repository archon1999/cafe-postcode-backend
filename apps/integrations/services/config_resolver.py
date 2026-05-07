from apps.integrations.models import IntegrationConfig


class IntegrationConfigResolverService:
    def get_queryset(self, kind, restaurant):
        return IntegrationConfig.objects.filter(
            restaurant=restaurant,
            kind=kind,
            is_enabled=True,
        )

    def get_config(self, kind, restaurant):
        return (
            self.get_queryset(kind=kind, restaurant=restaurant)
            .order_by('-created_at')
            .first()
        )
