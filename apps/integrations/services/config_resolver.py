from apps.integrations.models import IntegrationConfig


class IntegrationConfigResolverService:
    def get_config(self, kind, restaurant, branch=None):
        queryset = IntegrationConfig.objects.filter(
            restaurant=restaurant,
            kind=kind,
            is_enabled=True,
        )
        if branch is not None:
            branch_config = queryset.filter(branch=branch).order_by('-created_at').first()
            if branch_config:
                return branch_config
        return queryset.filter(branch__isnull=True).order_by('-created_at').first()

    def ensure_mock_configs(self, restaurant, branch):
        for kind, provider in [
            (IntegrationConfig.Kind.FISCAL, 'mock-fiscal'),
            (IntegrationConfig.Kind.PAYMENT, 'mock-payment'),
            (IntegrationConfig.Kind.PRINTER, 'mock-printer'),
        ]:
            IntegrationConfig.objects.get_or_create(
                restaurant=restaurant,
                branch=branch,
                kind=kind,
                provider=provider,
                defaults={'mode': IntegrationConfig.Mode.MOCK, 'is_enabled': True},
            )

