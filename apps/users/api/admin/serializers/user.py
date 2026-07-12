from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from rest_framework import serializers

from apps.floor.models import Hall
from apps.users.helpers import (
    get_employee_profile_model,
    get_restaurant_profile_model,
    get_role_model,
    get_user_model,
)
from apps.users.selectors.users import (
    role_is_allowed_for_employee_surface,
    role_requires_login_credentials,
)
from common.api.scopes import get_optional_request_restaurant

from .role import RoleSerializer

EmployeeProfile = get_employee_profile_model()
RestaurantProfile = get_restaurant_profile_model()
Role = get_role_model()
User = get_user_model()


def get_optional_restaurant_profile(instance):
    if instance is None:
        return None
    try:
        return instance.restaurant_profile
    except ObjectDoesNotExist:
        return None


class UserSerializer(serializers.ModelSerializer):
    user_surface = 'system'
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(source='role', queryset=Role.objects.all(), write_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
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
    hall_switch_permission = serializers.BooleanField(source='restaurant_profile.hall_switch_permission', required=False)
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
            'business_partner_id',
            'hall_switch_permission',
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
        )
        read_only_fields = ('restaurant_id', 'business_partner_id')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user_surface == 'employee':
            self.fields['username'].required = False
            self.fields['username'].allow_blank = True

    def _get_target_restaurant(self):
        request = self.context.get('request')
        request_restaurant = get_optional_request_restaurant(request) if request is not None else None
        if request_restaurant is not None:
            return request_restaurant

        if self.instance is not None:
            restaurant = self.instance.get_restaurant_scope()
            if restaurant is not None:
                return restaurant

        if request is not None and getattr(request.user, 'is_authenticated', False):
            return request.user.get_restaurant_scope()

        return None

    def _generate_internal_username(self, full_name: str, restaurant=None, instance: User | None = None) -> str:
        person_slug = slugify(full_name) or 'employee'
        restaurant_slug = slugify(getattr(restaurant, 'name', '')) or 'restaurant'
        base_username = f'{restaurant_slug}-{person_slug}'
        username = base_username[:150]
        suffix = 2

        queryset = User.objects.all()
        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)

        while queryset.filter(username=username).exists():
            suffix_text = f'-{suffix}'
            username = f'{base_username[: max(1, 150 - len(suffix_text))]}{suffix_text}'
            suffix += 1

        return username

    def get_restaurant_id(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, 'id', None)

    def get_business_partner_id(self, instance):
        business_partner = instance.get_business_partner_scope()
        return getattr(business_partner, 'id', None)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        request_data = getattr(request, 'data', {}) or {}
        pin = request_data.get('pin')
        password = request_data.get('password')
        restaurant = self._get_target_restaurant()
        role = attrs.get('role', getattr(self.instance, 'role', None))
        requires_login_credentials = self.user_surface == 'employee' and role_requires_login_credentials(role)
        restaurant_profile_data = attrs.get('restaurant_profile', {}) or {}
        current_restaurant_profile = get_optional_restaurant_profile(self.instance)
        primary_hall = restaurant_profile_data.get(
            'primary_hall',
            getattr(current_restaurant_profile, 'primary_hall', None),
        )

        if 'allowed_halls' in restaurant_profile_data:
            allowed_halls = list(restaurant_profile_data['allowed_halls'])
        elif current_restaurant_profile is not None:
            allowed_halls = list(current_restaurant_profile.allowed_halls.all())
        else:
            allowed_halls = []

        if self.user_surface == 'employee' and restaurant is None:
            raise serializers.ValidationError({'detail': _('Employees must belong to a restaurant scope.')})

        if self.user_surface == 'employee' and role is not None and not role_is_allowed_for_employee_surface(role):
            raise serializers.ValidationError({'roleId': _('Selected role is not available for employees.')})

        if requires_login_credentials:
            errors = {}
            username = attrs.get('username', getattr(self.instance, 'username', ''))
            if isinstance(username, str):
                username = username.strip()
            if not username:
                errors['username'] = _('Username is required for admin employees.')
            else:
                attrs['username'] = username

            if self.instance is None and (not isinstance(password, str) or not password.strip()):
                errors['password'] = _('Password is required for admin employees.')

            if pin not in (None, ''):
                errors['pin'] = _('PIN code is not used for admin employees.')

            if errors:
                raise serializers.ValidationError(errors)

        if isinstance(password, str) and password:
            try:
                validate_password(password, user=self.instance)
            except DjangoValidationError as error:
                raise serializers.ValidationError({'password': list(error.messages)}) from error

        if restaurant is not None and primary_hall is not None and primary_hall.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'primaryHallId': _('Selected hall does not belong to the selected restaurant.')})

        if restaurant is not None and any(hall.restaurant_id != restaurant.id for hall in allowed_halls):
            raise serializers.ValidationError({'allowedHallIds': _('All allowed halls must belong to the selected restaurant.')})

        if restaurant is not None and role is not None and not getattr(getattr(request, 'user', None), 'is_superuser', False):
            entitlement = getattr(restaurant, 'entitlement', None)
            allowed_role_ids = set()
            if entitlement is not None:
                allowed_role_ids.update(entitlement.allowed_roles.values_list('id', flat=True))
                if entitlement.tariff_id:
                    allowed_role_ids.update(entitlement.tariff.allowed_roles.values_list('id', flat=True))
            if role.id not in allowed_role_ids:
                raise serializers.ValidationError({'roleId': _('Selected role is not available for this restaurant.')})

        if pin in (None, ''):
            return attrs

        if not isinstance(pin, str):
            raise serializers.ValidationError({'pin': _('PIN code must be a string.')})
        if not pin.isdigit():
            raise serializers.ValidationError({'pin': _('PIN code must contain only digits.')})
        if len(pin) != 4:
            raise serializers.ValidationError({'pin': _('PIN code must be exactly 4 digits.')})

        duplicate_users = User.objects.exclude(restaurant_profile__pin_code='').select_related('role', 'restaurant_profile')
        if restaurant is not None:
            duplicate_users = duplicate_users.filter(restaurant_profile__restaurant=restaurant)
        if self.instance:
            duplicate_users = duplicate_users.exclude(pk=self.instance.pk)

        if any(user.check_pin(pin) for user in duplicate_users):
            raise serializers.ValidationError({'pin': _('This PIN code is already assigned to another POS user.')})

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        profile = getattr(instance, 'employee_profile', None)
        restaurant_profile = get_optional_restaurant_profile(instance)

        data['passport_series'] = profile.passport_series if profile else ''
        data['pnfl'] = profile.pnfl if profile else ''
        data['birth_date'] = profile.birth_date.isoformat() if profile and profile.birth_date else None
        data['employment_status'] = profile.employment_status if profile else EmployeeProfile.EmploymentStatus.ACTIVE
        data['salary_type'] = profile.salary_type if profile and profile.salary_type else None
        data['base_amount'] = float(profile.base_amount) if profile and profile.base_amount is not None else None
        data['kpi_percent'] = profile.kpi_percent if profile else None
        data['primary_hall_id'] = getattr(restaurant_profile, 'primary_hall_id', None)
        data['allowed_hall_ids'] = (
            list(restaurant_profile.allowed_halls.values_list('id', flat=True)) if restaurant_profile else []
        )
        data['hall_switch_permission'] = bool(getattr(restaurant_profile, 'hall_switch_permission', False))
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
            raise serializers.ValidationError({'baseAmount': _('Base amount is required for the selected salary type.')})
        if base_amount is not None and base_amount < 0:
            raise serializers.ValidationError({'baseAmount': _('Base amount must be greater than or equal to 0.')})
        if kpi_percent is not None and kpi_percent < 0:
            raise serializers.ValidationError({'kpiPercent': _('KPI percent must be greater than or equal to 0.')})

    @staticmethod
    def _save_profile(instance, profile_data):
        profile, _ = EmployeeProfile.objects.get_or_create(user=instance)
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()

    def _save_restaurant_profile(self, instance, restaurant_profile_data, pin, *, clear_pin=False):
        restaurant = restaurant_profile_data.pop('restaurant', None) or instance.get_restaurant_scope()
        if restaurant is None:
            return None

        restaurant_profile, _ = RestaurantProfile.objects.get_or_create(
            user=instance,
            defaults={'restaurant': restaurant},
        )
        if restaurant_profile.restaurant_id != restaurant.id:
            restaurant_profile.restaurant = restaurant

        if 'hall_switch_permission' in restaurant_profile_data:
            restaurant_profile.hall_switch_permission = restaurant_profile_data['hall_switch_permission']
        if 'primary_hall' in restaurant_profile_data:
            restaurant_profile.primary_hall = restaurant_profile_data['primary_hall']

        restaurant_profile.save()

        allowed_halls = restaurant_profile_data.get('allowed_halls')
        if allowed_halls is not None:
            restaurant_profile.allowed_halls.set(allowed_halls)

        if clear_pin:
            instance.pin_code = ''
            instance.save(update_fields=['pin_code'])
            restaurant_profile.pin_code = ''
            restaurant_profile.save(update_fields=['pin_code'])
        elif pin:
            instance.set_pin(pin)
        return restaurant_profile

    def create(self, validated_data):
        restaurant_profile_data = validated_data.pop('restaurant_profile', {})
        restaurant = validated_data.pop('restaurant', None)
        role = validated_data.get('role')
        requires_login_credentials = self.user_surface == 'employee' and role_requires_login_credentials(role)
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

        request = self.context.get('request')
        password = request.data.get('password') if request else None
        pin = request.data.get('pin') if request else None
        restaurant = restaurant or (self._get_target_restaurant() if self.user_surface == 'employee' else None)
        if restaurant is not None:
            restaurant_profile_data['restaurant'] = restaurant
        if self.user_surface == 'employee' and not requires_login_credentials:
            validated_data['username'] = self._generate_internal_username(
                validated_data.get('full_name', ''),
                restaurant=restaurant,
            )

        user = User.objects.create(**validated_data)

        if self.user_surface == 'employee':
            if requires_login_credentials:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.save(update_fields=['password'])
        elif password:
            user.set_password(password)
            user.save(update_fields=['password'])

        self._save_restaurant_profile(
            user,
            restaurant_profile_data,
            pin if not requires_login_credentials else None,
            clear_pin=requires_login_credentials,
        )
        self._save_profile(user, profile_data)
        user.refresh_from_db()
        return user

    def update(self, instance, validated_data):
        restaurant_profile_data = validated_data.pop('restaurant_profile', {})
        restaurant = validated_data.pop('restaurant', None)
        role = validated_data.get('role', instance.role)
        requires_login_credentials = self.user_surface == 'employee' and role_requires_login_credentials(role)
        if restaurant is not None:
            restaurant_profile_data['restaurant'] = restaurant
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

        if self.user_surface == 'employee' and not requires_login_credentials:
            validated_data.pop('username', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        request = self.context.get('request')
        password = request.data.get('password') if request else None
        pin = request.data.get('pin') if request else None
        if self.user_surface == 'employee':
            if requires_login_credentials and password:
                instance.set_password(password)
            elif not requires_login_credentials:
                instance.set_unusable_password()
        elif password:
            instance.set_password(password)
        instance.save()

        self._save_restaurant_profile(
            instance,
            restaurant_profile_data,
            pin if not requires_login_credentials else None,
            clear_pin=requires_login_credentials,
        )
        self._save_profile(instance, profile_data)
        instance.refresh_from_db()
        return instance


class EmployeeSerializer(UserSerializer):
    user_surface = 'employee'
