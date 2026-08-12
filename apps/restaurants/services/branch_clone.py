from copy import deepcopy
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from apps.catalog.models import (
    CatalogCategory,
    CatalogItem,
    CatalogItemModifierGroup,
    ModifierGroup,
    ModifierOption,
)
from apps.printing.models import PrintTemplate, PrintTemplateVersion
from apps.restaurants.models import PrepStation


BASE_EXCLUDED_FIELDS = {'id', 'created_at', 'updated_at'}
SAFE_RESTAURANT_SETTING_FIELDS = (
    'service_fee_enabled',
    'service_fee_percent',
    'vat_enabled',
    'vat_percent',
    'marking_check_enabled',
    'pos_monitor_variant',
    'payment_total_mode',
)


def _copy_concrete_values(instance, *, exclude=()) -> dict:
    excluded = BASE_EXCLUDED_FIELDS | set(exclude)
    return {
        field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields
        if field.name not in excluded and field.attname not in excluded
    }


def _copy_file(source_field, target_instance, field_name: str) -> None:
    if not source_field or not getattr(source_field, 'name', ''):
        return

    source_field.open('rb')
    try:
        content = ContentFile(source_field.read())
    finally:
        source_field.close()
    getattr(target_instance, field_name).save(
        Path(source_field.name).name,
        content,
        save=True,
    )


class RestaurantBranchCloneService:
    @transaction.atomic
    def clone(self, *, parent, branch, copy_catalog: bool, copy_settings: bool) -> dict:
        prep_station_map = {}

        if copy_settings:
            self._copy_restaurant_settings(parent=parent, branch=branch)
            prep_station_map = self._copy_prep_stations(parent=parent, branch=branch)
            self._copy_print_templates(parent=parent, branch=branch)

        if copy_catalog:
            if not prep_station_map:
                prep_station_map = self._copy_prep_stations(parent=parent, branch=branch)
            catalog_counts = self._copy_catalog(
                parent=parent,
                branch=branch,
                prep_station_map=prep_station_map,
            )
        else:
            catalog_counts = {
                'categories': 0,
                'items': 0,
                'modifier_groups': 0,
                'modifier_options': 0,
            }

        return {
            'prep_stations': len(prep_station_map),
            **catalog_counts,
        }

    @staticmethod
    def _copy_restaurant_settings(*, parent, branch) -> None:
        for field_name in SAFE_RESTAURANT_SETTING_FIELDS:
            setattr(branch, field_name, getattr(parent, field_name))
        branch.save(update_fields=(*SAFE_RESTAURANT_SETTING_FIELDS, 'updated_at'))
        _copy_file(parent.pos_auth_background_image, branch, 'pos_auth_background_image')

    @staticmethod
    def _copy_prep_stations(*, parent, branch) -> dict:
        mapping = {}
        for source in parent.prep_stations.order_by('created_at'):
            target = PrepStation.objects.create(
                restaurant=branch,
                name=source.name,
                kind=source.kind,
                is_active=source.is_active,
            )
            mapping[source.id] = target
        return mapping

    @staticmethod
    def _copy_print_templates(*, parent, branch) -> None:
        source_templates = parent.print_templates.select_related('published_version')
        for source_template in source_templates:
            source_version = source_template.published_version
            if source_version is None:
                continue

            target_template, _ = PrintTemplate.objects.get_or_create(
                restaurant=branch,
                kind=source_template.kind,
            )
            target_template.versions.filter(
                status=PrintTemplateVersion.Status.PUBLISHED
            ).update(status=PrintTemplateVersion.Status.RETIRED, updated_at=timezone.now())
            revision = (
                target_template.versions.aggregate(value=Max('revision'))['value'] or 0
            ) + 1
            target_version = PrintTemplateVersion.objects.create(
                template=target_template,
                revision=revision,
                schema_version=source_version.schema_version,
                status=PrintTemplateVersion.Status.PUBLISHED,
                preset_key=source_version.preset_key,
                layout=deepcopy(source_version.layout),
                published_at=timezone.now(),
            )
            target_template.published_version = target_version
            target_template.save(update_fields=('published_version', 'updated_at'))

    def _copy_catalog(self, *, parent, branch, prep_station_map: dict) -> dict:
        modifier_group_map = {}
        modifier_option_count = 0
        for source_group in parent.modifier_groups.order_by('created_at'):
            target_group = ModifierGroup.objects.create(
                restaurant=branch,
                **_copy_concrete_values(source_group, exclude=('restaurant',)),
            )
            modifier_group_map[source_group.id] = target_group
            for source_option in source_group.options.order_by('created_at'):
                ModifierOption.objects.create(
                    group=target_group,
                    **_copy_concrete_values(source_option, exclude=('group',)),
                )
                modifier_option_count += 1

        category_map = {}
        for source_category in parent.catalog_categories.order_by('created_at'):
            target_category = CatalogCategory.objects.create(
                restaurant=branch,
                prep_station=prep_station_map.get(source_category.prep_station_id),
                **_copy_concrete_values(
                    source_category,
                    exclude=('restaurant', 'prep_station', 'image_file'),
                ),
            )
            _copy_file(source_category.image_file, target_category, 'image_file')
            category_map[source_category.id] = target_category

        item_map = {}
        for source_item in parent.catalog_items.order_by('created_at'):
            values = _copy_concrete_values(
                source_item,
                exclude=(
                    'restaurant',
                    'category',
                    'prep_station',
                    'image_file',
                    'is_stoplisted',
                ),
            )
            target_item = CatalogItem.objects.create(
                restaurant=branch,
                category=category_map.get(source_item.category_id),
                prep_station=prep_station_map.get(source_item.prep_station_id),
                is_stoplisted=False,
                **values,
            )
            _copy_file(source_item.image_file, target_item, 'image_file')
            item_map[source_item.id] = target_item

        assignments = []
        for source_assignment in CatalogItemModifierGroup.objects.filter(
            catalog_item__restaurant=parent
        ).order_by('created_at'):
            target_item = item_map.get(source_assignment.catalog_item_id)
            target_group = modifier_group_map.get(source_assignment.modifier_group_id)
            if target_item is None or target_group is None:
                continue
            assignments.append(
                CatalogItemModifierGroup(
                    catalog_item=target_item,
                    modifier_group=target_group,
                    sort_order=source_assignment.sort_order,
                )
            )
        CatalogItemModifierGroup.objects.bulk_create(assignments)

        return {
            'categories': len(category_map),
            'items': len(item_map),
            'modifier_groups': len(modifier_group_map),
            'modifier_options': modifier_option_count,
        }


__all__ = ['RestaurantBranchCloneService']
