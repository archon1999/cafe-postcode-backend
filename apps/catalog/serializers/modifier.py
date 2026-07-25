from django.db import transaction
from rest_framework import serializers

from apps.catalog.models import ModifierGroup, ModifierOption
from common.api.scopes import get_optional_request_restaurant


class ModifierOptionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = ModifierOption
        fields = (
            "id",
            "name",
            "name_uz",
            "name_uz_crl",
            "name_ru",
            "price_delta",
            "is_default",
            "sort_order",
            "is_active",
        )


class PosModifierOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModifierOption
        fields = ("id", "name", "price_delta", "is_default", "sort_order")


class ModifierGroupSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    options = ModifierOptionSerializer(many=True)
    product_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = ModifierGroup
        fields = (
            "id",
            "restaurant_name",
            "name",
            "name_uz",
            "name_uz_crl",
            "name_ru",
            "selection_type",
            "min_selections",
            "max_selections",
            "sort_order",
            "is_active",
            "product_count",
            "options",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        selection_type = attrs.get(
            "selection_type",
            getattr(
                self.instance, "selection_type", ModifierGroup.SelectionType.SINGLE
            ),
        )
        min_selections = attrs.get(
            "min_selections", getattr(self.instance, "min_selections", 0)
        )
        max_selections = attrs.get(
            "max_selections", getattr(self.instance, "max_selections", 1)
        )
        if max_selections < 1:
            raise serializers.ValidationError(
                {"max_selections": "At least one selection must be allowed."}
            )
        if min_selections > max_selections:
            raise serializers.ValidationError(
                {
                    "min_selections": "Minimum selections cannot exceed maximum selections."
                }
            )
        if selection_type == ModifierGroup.SelectionType.SINGLE and max_selections != 1:
            raise serializers.ValidationError(
                {
                    "max_selections": "Single-choice groups must allow exactly one selection."
                }
            )

        options = attrs.get("options")
        if options is not None:
            active_options = [
                option for option in options if option.get("is_active", True)
            ]
            if not active_options:
                raise serializers.ValidationError(
                    {"options": "Add at least one active option."}
                )
            if min_selections > len(active_options):
                raise serializers.ValidationError(
                    {"min_selections": "Minimum selections exceed active options."}
                )
            names = [
                str(option.get("name") or "").strip().casefold() for option in options
            ]
            if len(names) != len(set(names)):
                raise serializers.ValidationError(
                    {"options": "Option names must be unique within a group."}
                )
            default_count = sum(
                bool(option.get("is_default", False)) for option in active_options
            )
            if default_count > max_selections:
                raise serializers.ValidationError(
                    {"options": "Default options exceed the maximum selection count."}
                )
        return attrs

    @staticmethod
    def _save_options(group, option_rows):
        retained_ids = set()
        existing_by_name = {
            option.name.strip().casefold(): option for option in group.options.all()
        }
        for row in option_rows:
            option_id = row.pop("id", None)
            option = group.options.filter(pk=option_id).first() if option_id else None
            if option is None:
                option = existing_by_name.get(
                    str(row.get("name") or "").strip().casefold()
                )
            if option is None:
                option = ModifierOption(group=group)
            for field, value in row.items():
                setattr(option, field, value)
            option.save()
            retained_ids.add(option.id)
        group.options.exclude(pk__in=retained_ids).update(is_active=False)

    @transaction.atomic
    def create(self, validated_data):
        option_rows = validated_data.pop("options", [])
        group = ModifierGroup.objects.create(**validated_data)
        self._save_options(group, option_rows)
        return group

    @transaction.atomic
    def update(self, instance, validated_data):
        option_rows = validated_data.pop("options", None)
        instance = super().update(instance, validated_data)
        if option_rows is not None:
            self._save_options(instance, option_rows)
        return instance


class PosModifierGroupSerializer(serializers.ModelSerializer):
    options = serializers.SerializerMethodField()

    class Meta:
        model = ModifierGroup
        fields = (
            "id",
            "name",
            "selection_type",
            "min_selections",
            "max_selections",
            "sort_order",
            "options",
        )

    @staticmethod
    def get_options(obj):
        prefetched_options = getattr(obj, "active_options", None)
        if prefetched_options is None:
            prefetched_options = obj.options.filter(is_active=True).order_by(
                "sort_order", "name"
            )
        return PosModifierOptionSerializer(prefetched_options, many=True).data
