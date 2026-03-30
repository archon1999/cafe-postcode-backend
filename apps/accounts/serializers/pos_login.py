from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import EmployeeProfile, User
from apps.organizations.models import Restaurant


class PosLoginSerializer(serializers.Serializer):
    restaurant_id = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.filter(is_active=True))
    pin = serializers.CharField(min_length=4, max_length=4, trim_whitespace=True)

    def validate_pin(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(_('PIN code must contain only digits.'))
        return value

    def validate(self, attrs):
        restaurant = attrs['restaurant_id']
        candidate_users = User.objects.filter(
            Q(restaurant_profile__restaurant=restaurant) | Q(restaurant=restaurant)
        ).select_related(
            'role',
            'employee_profile',
            'restaurant',
            'restaurant_profile__restaurant',
        )
        matched_users = [user for user in candidate_users.distinct() if user.can_access_pos_ui and user.check_pin(attrs['pin'])]

        if not matched_users:
            raise serializers.ValidationError({'pin': _('Invalid PIN code.')})

        if len(matched_users) > 1:
            raise serializers.ValidationError(
                {'pin': _('This PIN code is assigned to multiple POS users. Use unique PIN codes.')}
            )

        matched_user = matched_users[0]
        employment_status = getattr(
            getattr(matched_user, 'employee_profile', None),
            'employment_status',
            EmployeeProfile.EmploymentStatus.ACTIVE,
        )

        if employment_status == EmployeeProfile.EmploymentStatus.ARCHIVED:
            raise serializers.ValidationError({'pin': _('This employee is archived and cannot sign in.')})

        if not matched_user.is_active or employment_status != EmployeeProfile.EmploymentStatus.ACTIVE:
            raise serializers.ValidationError({'pin': _('This employee is inactive and cannot sign in.')})

        attrs['user'] = matched_user
        attrs['restaurant'] = restaurant
        return attrs
