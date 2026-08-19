from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from rest_framework import serializers

from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.users.helpers import get_role_model, get_user_model

RestaurantEntitlement = get_restaurant_entitlement_model()
Role = get_role_model()
Tariff = get_tariff_model()
User = get_user_model()


def _role_payload(role):
    if role is None:
        return None
    return {
        'id': str(role.id),
        'code': role.code,
        'name': role.name,
    }


def _employee_payload(user):
    return {
        'id': str(user.id),
        'username': user.username,
        'full_name': user.full_name,
        'is_active': user.is_active,
    }


def get_restaurant_tariff_change_preview(*, restaurant, target_tariff):
    allowed_roles = list(target_tariff.allowed_roles.all().order_by('name', 'code'))
    allowed_role_ids = {role.id for role in allowed_roles}
    users = list(
        User.objects.filter(
            restaurant_profile__restaurant=restaurant,
            is_superuser=False,
        )
        .select_related('role')
        .order_by('role__name', 'full_name', 'username')
        .distinct()
    )

    grouped_users = defaultdict(list)
    source_roles = {}
    for user in users:
        grouped_users[user.role_id].append(user)
        source_roles[user.role_id] = user.role

    role_groups = []
    for source_role_id, grouped in grouped_users.items():
        source_role = source_roles[source_role_id]
        suggested_target = source_role if source_role_id in allowed_role_ids else None
        role_groups.append(
            {
                'source_role': _role_payload(source_role),
                'suggested_target_role': _role_payload(suggested_target),
                'employee_count': len(grouped),
                'employees': [_employee_payload(user) for user in grouped],
            }
        )

    current_entitlement = getattr(restaurant, 'entitlement', None)
    current_tariff = current_entitlement.tariff if current_entitlement else None
    return {
        'restaurant': {'id': str(restaurant.id), 'name': restaurant.name},
        'current_tariff': (
            {'id': str(current_tariff.id), 'name': current_tariff.name}
            if current_tariff is not None
            else None
        ),
        'target_tariff': {
            'id': str(target_tariff.id),
            'name': target_tariff.name,
            'allowed_roles': [_role_payload(role) for role in allowed_roles],
        },
        'role_groups': role_groups,
    }


@transaction.atomic
def change_restaurant_tariff(*, restaurant, target_tariff, role_mappings):
    locked_users = list(
        User.objects.select_for_update()
        .filter(
            restaurant_profile__restaurant=restaurant,
            is_superuser=False,
        )
        .select_related('role')
        .distinct()
    )
    source_role_ids = {user.role_id for user in locked_users}

    mapping_by_source = {}
    for mapping in role_mappings:
        source_role_id = mapping.get('source_role_id')
        target_role_id = mapping.get('target_role_id')
        if source_role_id in mapping_by_source:
            raise serializers.ValidationError(
                {'roleMappings': 'Har bir mavjud rol uchun faqat bitta mapping yuboring.'}
            )
        mapping_by_source[source_role_id] = target_role_id

    if set(mapping_by_source) != source_role_ids:
        raise serializers.ValidationError(
            {'roleMappings': 'Barcha mavjud xodim rollari uchun mapping yuborilishi shart.'}
        )

    allowed_role_ids = set(target_tariff.allowed_roles.values_list('id', flat=True))
    invalid_target_ids = set(mapping_by_source.values()) - allowed_role_ids
    if invalid_target_ids:
        raise serializers.ValidationError(
            {'roleMappings': 'Tanlangan yangi rol maqsad tarifda ruxsat etilmagan.'}
        )

    updated_users = 0
    for source_role_id, target_role_id in mapping_by_source.items():
        user_ids = [user.id for user in locked_users if user.role_id == source_role_id]
        if user_ids:
            updated_users += User.objects.filter(id__in=user_ids).update(role_id=target_role_id)

    entitlement, _ = RestaurantEntitlement.objects.select_for_update().get_or_create(
        restaurant=restaurant
    )
    entitlement.tariff = target_tariff
    entitlement.is_custom = False
    entitlement.save(update_fields=['tariff', 'is_custom', 'updated_at'])
    entitlement.permissions.clear()
    entitlement.allowed_roles.clear()

    return updated_users
