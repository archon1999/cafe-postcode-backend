from django.db import transaction
from django.db.models import Max
from rest_framework import serializers

from apps.catalog.models import CatalogItem, CatalogItemGroup, CatalogItemGroupMember
from common.api.scopes import get_optional_request_restaurant

from .pos_catalog_item import PosCatalogItemSerializer


class CatalogItemGroupMemberSerializer(serializers.ModelSerializer):
    catalog_item_name = serializers.CharField(source='catalog_item.name', read_only=True)
    price = serializers.IntegerField(source='catalog_item.price', read_only=True)
    is_active = serializers.BooleanField(source='catalog_item.is_active', read_only=True)
    is_stoplisted = serializers.BooleanField(source='catalog_item.is_stoplisted', read_only=True)

    class Meta:
        model = CatalogItemGroupMember
        fields = (
            'id',
            'catalog_item',
            'catalog_item_name',
            'variant_name',
            'price',
            'is_active',
            'is_stoplisted',
            'sort_order',
        )


class CatalogItemGroupSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    members = CatalogItemGroupMemberSerializer(many=True)

    class Meta:
        model = CatalogItemGroup
        fields = (
            'id',
            'category',
            'category_name',
            'name',
            'description',
            'sort_order',
            'is_active',
            'members',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        restaurant = get_optional_request_restaurant(request) if request else None
        if restaurant is not None:
            self.fields['category'].queryset = restaurant.catalog_categories.all()
            self.fields['members'].child.fields['catalog_item'].queryset = restaurant.catalog_items.all()

    def validate_members(self, members):
        if len(members) < 2:
            raise serializers.ValidationError('A group must contain at least two products.')
        item_ids = [member['catalog_item'].id for member in members]
        if len(item_ids) != len(set(item_ids)):
            raise serializers.ValidationError('A product can be selected only once.')
        return members

    def validate(self, attrs):
        attrs = super().validate(attrs)
        category = attrs.get('category', getattr(self.instance, 'category', None))
        members = attrs.get('members')
        if members is None:
            return attrs

        restaurant = category.restaurant if category else None
        errors = {}
        for index, member in enumerate(members):
            item = member['catalog_item']
            if restaurant and item.restaurant_id != restaurant.id:
                errors[index] = 'Product belongs to another restaurant.'
            elif item.category_id != getattr(category, 'id', None):
                errors[index] = 'All products must belong to the selected category.'
            elif CatalogItemGroupMember.objects.filter(catalog_item=item).exclude(
                group=self.instance
            ).exists():
                errors[index] = 'Product already belongs to another group.'
        if errors:
            raise serializers.ValidationError({'members': errors})
        return attrs

    @staticmethod
    def _replace_members(group, members):
        group.members.all().delete()
        CatalogItemGroupMember.objects.bulk_create(
            [
                CatalogItemGroupMember(
                    group=group,
                    catalog_item=member['catalog_item'],
                    variant_name=member.get('variant_name', ''),
                    sort_order=index,
                )
                for index, member in enumerate(members)
            ]
        )

    @transaction.atomic
    def create(self, validated_data):
        members = validated_data.pop('members')
        if 'sort_order' not in validated_data:
            current_max = CatalogItemGroup.objects.filter(
                restaurant=validated_data['restaurant'],
                category=validated_data['category'],
            ).aggregate(value=Max('sort_order'))['value']
            validated_data['sort_order'] = (current_max if current_max is not None else -1) + 1
        group = super().create(validated_data)
        self._replace_members(group, members)
        return group

    @transaction.atomic
    def update(self, instance, validated_data):
        members = validated_data.pop('members', None)
        group = super().update(instance, validated_data)
        if members is not None:
            self._replace_members(group, members)
        return group


class PosCatalogItemGroupMemberSerializer(serializers.ModelSerializer):
    item = PosCatalogItemSerializer(source='catalog_item', read_only=True)

    class Meta:
        model = CatalogItemGroupMember
        fields = ('id', 'variant_name', 'sort_order', 'item')


class PosCatalogItemGroupSerializer(serializers.ModelSerializer):
    members = PosCatalogItemGroupMemberSerializer(many=True, read_only=True)

    class Meta:
        model = CatalogItemGroup
        fields = ('id', 'name', 'description', 'sort_order', 'members')
