from apps.integrations.models import IntegrationConfig


class IntegrationConfigResolverService:
    def get_config(self, kind, restaurant):
        return (
            IntegrationConfig.objects.filter(
                restaurant=restaurant,
                kind=kind,
                is_enabled=True,
            )
            .order_by('-created_at')
            .first()
        )

    def ensure_mock_configs(self, restaurant):
        for kind, provider in [
            (IntegrationConfig.Kind.FISCAL, 'mock-fiscal'),
            (IntegrationConfig.Kind.PAYMENT, 'mock-payment'),
            (IntegrationConfig.Kind.PRINTER, 'mock-printer'),
        ]:
            IntegrationConfig.objects.get_or_create(
                restaurant=restaurant,
                kind=kind,
                provider=provider,
                defaults={'mode': IntegrationConfig.Mode.MOCK, 'is_enabled': True},
            )
