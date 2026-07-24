from django.db.models import Prefetch

from apps.catalog.models import CatalogItemModifierGroup, ModifierOption


def active_modifier_assignments_prefetch():
    return Prefetch(
        'modifier_assignments',
        queryset=(
            CatalogItemModifierGroup.objects.filter(modifier_group__is_active=True)
            .select_related('modifier_group')
            .prefetch_related(
                Prefetch(
                    'modifier_group__options',
                    queryset=ModifierOption.objects.filter(is_active=True).order_by('sort_order', 'name'),
                    to_attr='active_options',
                )
            )
            .order_by('sort_order', 'modifier_group__sort_order', 'modifier_group__name')
        ),
        to_attr='active_modifier_assignments',
    )
