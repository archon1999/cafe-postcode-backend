from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalog.utils.marking import item_requires_marking
from apps.sales.helpers import get_order_item_model
from apps.catalog.utils.prep_station import resolve_order_item_prep_station
from apps.catalog.models import CatalogItem, CatalogItemModifierGroup
from apps.sales.models import OrderItemModifier
from common.api.scopes import get_optional_request_restaurant

from .order_item_modifier import OrderItemModifierSerializer, SelectedModifierGroupSerializer

OrderItem = get_order_item_model()


class QuantityDecimalField(serializers.DecimalField):
    def to_representation(self, value):
        quantity = Decimal(value or 0)
        if quantity == quantity.to_integral_value():
            return int(quantity)
        return float(quantity.normalize())


class OrderItemSerializer(serializers.ModelSerializer):
    COMMAND_ONLY_UPDATE_FIELDS = ('id', 'catalog_item', 'status')
    DISPATCHED_SNAPSHOT_FIELDS = ('catalog_item', 'quantity', 'status', 'note', 'selected_modifiers')

    id = serializers.UUIDField(required=False)
    catalog_item_name = serializers.CharField(source='catalog_item.name', read_only=True)
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)
    markings = serializers.SerializerMethodField()
    marking_required_count = serializers.SerializerMethodField()
    marking_scanned_count = serializers.SerializerMethodField()
    modifiers = OrderItemModifierSerializer(many=True, read_only=True)
    selected_modifiers = SelectedModifierGroupSerializer(many=True, write_only=True, required=False, default=list)
    kitchen_dispatched = serializers.SerializerMethodField()
    kitchen_dispatch_number = serializers.SerializerMethodField()
    quantity = QuantityDecimalField(max_digits=12, decimal_places=3)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return

        restaurant = get_optional_request_restaurant(request)
        if restaurant is not None:
            self.fields['catalog_item'].queryset = CatalogItem.objects.filter(
                restaurant=restaurant,
            )

    @staticmethod
    def _ticket_line(obj):
        try:
            return obj.kitchen_ticket_line
        except (AttributeError, ObjectDoesNotExist):
            return None

    def get_kitchen_dispatched(self, obj):
        return self._ticket_line(obj) is not None

    def get_kitchen_dispatch_number(self, obj):
        line = self._ticket_line(obj)
        return line.ticket.dispatch_number if line is not None else None

    def get_markings(self, obj):
        markings = getattr(obj, '_prefetched_objects_cache', {}).get('markings')
        if markings is None:
            markings = obj.markings.all()
        return [
            {
                'id': str(marking.id),
                'raw_code': marking.raw_code,
                'rawCode': marking.raw_code,
                'gtin': marking.gtin,
                'serial': marking.serial,
                'scanned_at': marking.scanned_at,
            }
            for marking in markings
        ]

    def get_marking_required_count(self, obj):
        if not obj.catalog_item_id or not item_requires_marking(obj.catalog_item):
            return 0
        return int(obj.quantity)

    def get_marking_scanned_count(self, obj):
        return len(self.get_markings(obj))

    def _is_trusted_edge_replay(self) -> bool:
        request = self.context.get('request')
        raw_request = getattr(request, '_request', request)
        return bool(getattr(raw_request, 'trusted_edge_replay', False))

    class Meta:
        model = OrderItem
        fields = (
            'id',
            'order',
            'catalog_item',
            'catalog_item_name',
            'prep_station',
            'prep_station_name',
            'quantity',
            'sale_unit',
            'base_unit_price',
            'unit_price',
            'line_total',
            'status',
            'note',
            'markings',
            'marking_required_count',
            'marking_scanned_count',
            'modifiers',
            'selected_modifiers',
            'kitchen_dispatched',
            'kitchen_dispatch_number',
            'created_at',
        )
        read_only_fields = ('order', 'sale_unit', 'base_unit_price', 'unit_price', 'line_total', 'prep_station')

    def validate(self, attrs):
        catalog_item = attrs.get('catalog_item') or getattr(self.instance, 'catalog_item', None)
        if self.instance is None:
            if catalog_item and not catalog_item.is_active:
                raise serializers.ValidationError({'catalog_item': _('This menu item is inactive.')})
            if catalog_item and catalog_item.is_stoplisted:
                raise serializers.ValidationError({'catalog_item': _('This menu item is in stoplist.')})
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', Decimal('1')))
        sale_unit = getattr(catalog_item, 'sale_unit', CatalogItem.SaleUnit.PIECE)
        if quantity is None or quantity <= 0:
            raise serializers.ValidationError({'quantity': _('Quantity must be greater than zero.')})
        if sale_unit == CatalogItem.SaleUnit.PIECE and quantity != quantity.to_integral_value():
            raise serializers.ValidationError({'quantity': _('Piece products require a whole-number quantity.')})
        if sale_unit == CatalogItem.SaleUnit.KILOGRAM and item_requires_marking(catalog_item):
            raise serializers.ValidationError({'catalog_item': _('Marked products cannot be sold by kilogram.')})
        if self.instance is not None:
            self.validate_update_constraints(instance=self.instance, attrs=attrs)
            return attrs

        errors = {}
        if 'id' in attrs:
            if not self._is_trusted_edge_replay():
                errors['id'] = _('Order item IDs are generated by the server.')
            elif OrderItem.objects.filter(pk=attrs['id']).exists():
                errors['id'] = _('An order item with this ID already exists.')
        if attrs.get('status', OrderItem.Status.NEW) != OrderItem.Status.NEW:
            errors['status'] = _('New order items must start in the new state.')
        if errors:
            raise serializers.ValidationError(errors)

        selections = attrs.pop('selected_modifiers', [])
        assignments = list(
            CatalogItemModifierGroup.objects.filter(
                catalog_item=catalog_item,
                modifier_group__is_active=True,
            )
            .select_related('modifier_group')
            .prefetch_related('modifier_group__options')
            .order_by('sort_order', 'modifier_group__sort_order', 'modifier_group__name')
        )
        assignments_by_id = {assignment.modifier_group_id: assignment for assignment in assignments}
        selected_by_group = {}
        for selection in selections:
            group_id = selection['group']
            if group_id in selected_by_group:
                raise serializers.ValidationError({'selected_modifiers': _('Each modifier group may be submitted only once.')})
            option_ids = selection['options']
            if len(option_ids) != len(set(option_ids)):
                raise serializers.ValidationError({'selected_modifiers': _('Modifier options cannot be duplicated.')})
            selected_by_group[group_id] = option_ids

        unknown_group_ids = set(selected_by_group) - set(assignments_by_id)
        if unknown_group_ids:
            raise serializers.ValidationError({'selected_modifiers': _('A selected modifier group is not assigned to this item.')})

        resolved = []
        for assignment in assignments:
            group = assignment.modifier_group
            option_ids = selected_by_group.get(group.id, [])
            if len(option_ids) < group.min_selections:
                raise serializers.ValidationError(
                    {'selected_modifiers': _('%(group)s requires at least %(count)s selection(s).') % {
                        'group': group.name,
                        'count': group.min_selections,
                    }}
                )
            if len(option_ids) > group.max_selections:
                raise serializers.ValidationError(
                    {'selected_modifiers': _('%(group)s allows at most %(count)s selection(s).') % {
                        'group': group.name,
                        'count': group.max_selections,
                    }}
                )
            active_options = {option.id: option for option in group.options.all() if option.is_active}
            invalid_option_ids = set(option_ids) - set(active_options)
            if invalid_option_ids:
                raise serializers.ValidationError(
                    {'selected_modifiers': _('%(group)s contains an unavailable option.') % {'group': group.name}}
                )
            resolved.extend((assignment, active_options[option_id]) for option_id in option_ids)
        attrs['_resolved_modifiers'] = resolved
        return attrs

    def validate_update_constraints(self, *, instance, attrs):
        errors = {
            field_name: _('This field cannot be changed after adding the item.')
            for field_name in self.COMMAND_ONLY_UPDATE_FIELDS
            if field_name in attrs
        }
        if self._ticket_line(instance) is not None:
            errors.update(
                {
                    field_name: _('Dispatched item snapshots cannot be changed.')
                    for field_name in self.DISPATCHED_SNAPSHOT_FIELDS
                    if field_name in attrs
                }
            )
        elif 'selected_modifiers' in attrs:
            errors['selected_modifiers'] = _('Modifiers cannot be changed after adding the item.')
        if 'quantity' in attrs and instance.markings.exists():
            errors.setdefault(
                'quantity',
                _('Quantity for a marked item can only be changed through marking scans.'),
            )
        if errors:
            raise serializers.ValidationError(errors)

    def create(self, validated_data):
        resolved_modifiers = validated_data.pop('_resolved_modifiers', [])
        catalog_item = validated_data['catalog_item']
        catalog_item = type(catalog_item).objects.select_related('category__prep_station', 'prep_station').get(
            pk=catalog_item.pk
        )
        base_unit_price = int(catalog_item.price or 0)
        validated_data['base_unit_price'] = base_unit_price
        validated_data['unit_price'] = base_unit_price + sum(int(option.price_delta or 0) for _, option in resolved_modifiers)
        validated_data['sale_unit'] = catalog_item.sale_unit
        order = validated_data.get('order')
        validated_data['prep_station'] = resolve_order_item_prep_station(
            catalog_item=catalog_item,
            restaurant=getattr(order, 'restaurant', None),
        )
        order_item = super().create(validated_data)
        OrderItemModifier.objects.bulk_create(
            [
                OrderItemModifier(
                    order_item=order_item,
                    modifier_option=option,
                    group_name=assignment.modifier_group.name,
                    option_name=option.name,
                    price_delta=int(option.price_delta or 0),
                    sort_order=(assignment.sort_order * 1000) + option.sort_order,
                )
                for assignment, option in resolved_modifiers
            ]
        )
        return order_item

    def update(self, instance, validated_data):
        update_fields = set(validated_data)
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        if update_fields:
            if 'quantity' in update_fields:
                update_fields.add('line_total')
            instance.save(update_fields=[*sorted(update_fields), 'updated_at'])
        return instance
