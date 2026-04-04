from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import EmployeeProfile, RestaurantProfile, Role, User
from apps.accounts.permission_registry import POS_UI_PERMISSION_CODES
from apps.floor.models import Hall

from .role import RoleSerializer


def get_optional_restaurant_profile(instance):
    try:
        return instance.restaurant_profile
    except ObjectDoesNotExist:
        return None


class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(source='role', queryset=Role.objects.all(), write_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    restaurant_access_active = serializers.BooleanField(read_only=True)
    restaurant_id = serializers.SerializerMethodField()
    business_partner_id = serializers.SerializerMethodField()
    primary_hall_id = serializers.PrimaryKeyRelatedField(
        source='restaurant_profile.primary_hall',
        queryset=Hall.objects.all(),
        required=False,
        allow_null=True,
    )
    allowed_hall_ids = serializers.PrimaryKeyRelatedField(
        source='restaurant_profile.allowed_halls',
        queryset=Hall.objects.all(),
        many=True,
        required=False,
    )
    passport_series = serializers.CharField(required=False, allow_blank=True, write_only=True)
    pnfl = serializers.CharField(required=False, allow_blank=True, write_only=True)
    birth_date = serializers.DateField(required=False, allow_null=True, write_only=True)
    employment_status = serializers.ChoiceField(
        choices=EmployeeProfile.EmploymentStatus.choices,
        required=False,
        write_only=True,
    )
    salary_type = serializers.ChoiceField(
        choices=EmployeeProfile.SalaryType.choices,
        required=False,
        allow_blank=True,
        write_only=True,
    )
    base_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        write_only=True,
    )
    kpi_percent = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'full_name',
            'phone',
            'is_active',
            'role',
            'role_id',
            'restaurant_id',
            'primary_hall_id',
            'allowed_hall_ids',
            'passport_series',
            'pnfl',
            'birth_date',
            'employment_status',
            'salary_type',
            'base_amount',
            'kpi_percent',
            'permission_codes',
            'restaurant_access_active',
            'business_partner_id',
        )
        read_only_fields = ('restaurant_id',)

    def validate(self, attrs):
        request_data = getattr(self.context.get('request'), 'data', {}) or {}
        pin = request_data.get('pin')

        if pin in (None, ''):
            return attrs

        if not isinstance(pin, str):
            raise serializers.ValidationError({'pin': _('PIN code must be a string.')})
        if not pin.isdigit():
            raise serializers.ValidationError({'pin': _('PIN code must contain only digits.')})
        if len(pin) != 4:
            raise serializers.ValidationError({'pin': _('PIN code must be exactly 4 digits.')})

        duplicate_users = User.objects.exclude(pin_code='').filter(role__permissions__code__in=POS_UI_PERMISSION_CODES).select_related('role').distinct()

        if self.instance:
            duplicate_users = duplicate_users.exclude(pk=self.instance.pk)

        if any(user.check_pin(pin) for user in duplicate_users):
            raise serializers.ValidationError({'pin': _('This PIN code is already assigned to another POS user.')})

        return attrs

    def get_restaurant_id(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, 'id', None)

    def get_business_partner_id(self, instance):
        business_partner = instance.get_business_partner_scope()
        return getattr(business_partner, 'id', None)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        profile = getattr(instance, 'employee_profile', None)
        restaurant_profile = get_optional_restaurant_profile(instance)

        data['passport_series'] = profile.passport_series if profile else ''
        data['pnfl'] = profile.pnfl if profile else ''
        data['birth_date'] = profile.birth_date.isoformat() if profile and profile.birth_date else None
        data['employment_status'] = (
            profile.employment_status if profile else EmployeeProfile.EmploymentStatus.ACTIVE
        )
        data['salary_type'] = profile.salary_type if profile and profile.salary_type else None
        data['base_amount'] = float(profile.base_amount) if profile and profile.base_amount is not None else None
        data['kpi_percent'] = profile.kpi_percent if profile else None
        data['primary_hall_id'] = getattr(restaurant_profile, 'primary_hall_id', None)
        data['allowed_hall_ids'] = (
            list(restaurant_profile.allowed_halls.values_list('id', flat=True)) if restaurant_profile else []
        )
        return data

    @staticmethod
    def _extract_profile_data(validated_data):
        return {
            key: validated_data.pop(key)
            for key in ('passport_series', 'pnfl', 'birth_date', 'employment_status')
            if key in validated_data
        }

    @staticmethod
    def _normalize_profile_status(validated_data, profile_data, current_status=EmployeeProfile.EmploymentStatus.ACTIVE):
        if 'employment_status' not in profile_data:
            profile_data['employment_status'] = current_status

        if profile_data['employment_status'] == EmployeeProfile.EmploymentStatus.ARCHIVED:
            validated_data['is_active'] = False
            return

        if 'is_active' in validated_data:
            profile_data['employment_status'] = (
                EmployeeProfile.EmploymentStatus.ACTIVE
                if validated_data['is_active']
                else EmployeeProfile.EmploymentStatus.INACTIVE
            )
            return

        validated_data['is_active'] = profile_data['employment_status'] == EmployeeProfile.EmploymentStatus.ACTIVE

    @staticmethod
    def _validate_compensation_data(profile_data):
        salary_type = profile_data.get('salary_type') or ''
        base_amount = profile_data.get('base_amount')
        kpi_percent = profile_data.get('kpi_percent')

        if salary_type and base_amount is None:
            raise serializers.ValidationError({'base_amount': _('Base amount is required for the selected salary type.')})
        if base_amount is not None and base_amount < 0:
            raise serializers.ValidationError({'base_amount': _('Base amount must be greater than or equal to 0.')})
        if kpi_percent is not None and kpi_percent < 0:
            raise serializers.ValidationError({'kpi_percent': _('KPI percent must be greater than or equal to 0.')})

    @staticmethod
    def _save_profile(instance, profile_data):
        profile, _ = EmployeeProfile.objects.get_or_create(user=instance)
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()

    def create(self, validated_data):
        restaurant = validated_data.pop('restaurant', None)
        restaurant_profile_data = validated_data.pop('restaurant_profile', {})
        profile_data = self._extract_profile_data(validated_data)
        profile_data.update(
            {
                key: validated_data.pop(key)
                for key in ('salary_type', 'base_amount', 'kpi_percent')
                if key in validated_data
            }
        )
        self._normalize_profile_status(validated_data, profile_data)
        self._validate_compensation_data(profile_data)
        password = self.context['request'].data.get('password')
        pin = self.context['request'].data.get('pin')
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
        if pin:
            user.set_pin(pin)
        user.save(update_fields=['password', 'pin_code'])
        if restaurant is not None:
            RestaurantProfile.objects.update_or_create(
                user=user,
                defaults={'restaurant': restaurant},
            )
        restaurant = user.get_restaurant_scope()
        if restaurant is not None:
            restaurant_profile = get_optional_restaurant_profile(user)
            if restaurant_profile is None:
                restaurant_profile = RestaurantProfile.objects.create(user=user, restaurant=restaurant)
            primary_hall = restaurant_profile_data.get('primary_hall')
            allowed_halls = restaurant_profile_data.get('allowed_halls')
            restaurant_profile.primary_hall = primary_hall
            restaurant_profile.save(update_fields=['primary_hall'])
            if allowed_halls is not None:
                restaurant_profile.allowed_halls.set(allowed_halls)
        self._save_profile(user, profile_data)
        user.refresh_from_db()
        return user

    def update(self, instance, validated_data):
        restaurant_profile_data = validated_data.pop('restaurant_profile', {})
        profile_data = self._extract_profile_data(validated_data)
        profile_data.update(
            {
                key: validated_data.pop(key)
                for key in ('salary_type', 'base_amount', 'kpi_percent')
                if key in validated_data
            }
        )
        current_status = getattr(
            getattr(instance, 'employee_profile', None),
            'employment_status',
            EmployeeProfile.EmploymentStatus.ACTIVE,
        )
        self._normalize_profile_status(validated_data, profile_data, current_status=current_status)
        self._validate_compensation_data(profile_data)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        password = self.context['request'].data.get('password')
        pin = self.context['request'].data.get('pin')
        if password:
            instance.set_password(password)
        if pin:
            instance.set_pin(pin)
        instance.save()
        restaurant_profile = get_optional_restaurant_profile(instance)
        primary_hall = restaurant_profile_data.get('primary_hall', serializers.empty)
        allowed_halls = restaurant_profile_data.get('allowed_halls', None)
        if restaurant_profile is not None and primary_hall is not serializers.empty:
            restaurant_profile.primary_hall = primary_hall
            restaurant_profile.save(update_fields=['primary_hall'])
        if restaurant_profile is not None and allowed_halls is not None:
            restaurant_profile.allowed_halls.set(allowed_halls)
        self._save_profile(instance, profile_data)
        instance.refresh_from_db()
        return instance
