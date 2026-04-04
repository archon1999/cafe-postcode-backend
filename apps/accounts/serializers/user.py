from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import EmployeeCompensationProfile, EmployeeProfile, Role, User
from apps.floor.models import Hall

from .role import RoleSerializer


class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(source='role', queryset=Role.objects.all(), write_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    actor_type = serializers.CharField(read_only=True)
    restaurant_access_active = serializers.BooleanField(read_only=True)
    restaurant_id = serializers.UUIDField(read_only=True)
    business_partner_id = serializers.UUIDField(read_only=True)
    primary_hall_id = serializers.PrimaryKeyRelatedField(source='primary_hall', queryset=Hall.objects.all(), required=False, allow_null=True)
    allowed_hall_ids = serializers.PrimaryKeyRelatedField(source='allowed_halls', queryset=Hall.objects.all(), many=True, required=False)
    passport_series = serializers.CharField(required=False, allow_blank=True, write_only=True)
    pnfl = serializers.CharField(required=False, allow_blank=True, write_only=True)
    birth_date = serializers.DateField(required=False, allow_null=True, write_only=True)
    employment_status = serializers.ChoiceField(
        choices=EmployeeProfile.EmploymentStatus.choices,
        required=False,
        write_only=True,
    )
    salary_type = serializers.ChoiceField(
        choices=EmployeeCompensationProfile.SalaryType.choices,
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
            'ui_mode',
            'is_active',
            'role',
            'role_id',
            'restaurant_id',
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
            'actor_type',
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

        duplicate_users = (
            User.objects.exclude(pin_code='')
            .filter(Q(ui_mode=User.UiMode.POS) | Q(is_superuser=True))
            .select_related('role')
        )

        if self.instance:
            duplicate_users = duplicate_users.exclude(pk=self.instance.pk)

        if any(user.check_pin(pin) for user in duplicate_users):
            raise serializers.ValidationError({'pin': _('This PIN code is already assigned to another POS user.')})

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        profile = getattr(instance, 'employee_profile', None)
        compensation = getattr(instance, 'employee_compensation_profile', None)

        data['passport_series'] = profile.passport_series if profile else ''
        data['pnfl'] = profile.pnfl if profile else ''
        data['birth_date'] = profile.birth_date.isoformat() if profile and profile.birth_date else None
        data['employment_status'] = (
            profile.employment_status if profile else EmployeeProfile.EmploymentStatus.ACTIVE
        )
        data['salary_type'] = compensation.salary_type if compensation and compensation.salary_type else None
        data['base_amount'] = float(compensation.base_amount) if compensation and compensation.base_amount is not None else None
        data['kpi_percent'] = compensation.kpi_percent if compensation else None
        return data

    @staticmethod
    def _extract_profile_data(validated_data):
        return {
            key: validated_data.pop(key)
            for key in ('passport_series', 'pnfl', 'birth_date', 'employment_status')
            if key in validated_data
        }

    @staticmethod
    def _extract_compensation_data(validated_data):
        return {
            key: validated_data.pop(key)
            for key in ('salary_type', 'base_amount', 'kpi_percent')
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
    def _validate_compensation_data(compensation_data):
        salary_type = compensation_data.get('salary_type') or ''
        base_amount = compensation_data.get('base_amount')
        kpi_percent = compensation_data.get('kpi_percent')

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

    @staticmethod
    def _save_compensation(instance, compensation_data):
        profile, _ = EmployeeCompensationProfile.objects.get_or_create(user=instance)
        for attr, value in compensation_data.items():
            setattr(profile, attr, value)
        profile.save()

    def create(self, validated_data):
        allowed_halls = validated_data.pop('allowed_halls', [])
        profile_data = self._extract_profile_data(validated_data)
        compensation_data = self._extract_compensation_data(validated_data)
        self._normalize_profile_status(validated_data, profile_data)
        self._validate_compensation_data(compensation_data)
        password = self.context['request'].data.get('password')
        pin = self.context['request'].data.get('pin')
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
        if pin:
            user.set_pin(pin)
        user.save(update_fields=['password', 'pin_code'])
        if allowed_halls:
            user.allowed_halls.set(allowed_halls)
        self._save_profile(user, profile_data)
        self._save_compensation(user, compensation_data)
        user.refresh_from_db()
        return user

    def update(self, instance, validated_data):
        allowed_halls = validated_data.pop('allowed_halls', None)
        profile_data = self._extract_profile_data(validated_data)
        compensation_data = self._extract_compensation_data(validated_data)
        current_status = getattr(
            getattr(instance, 'employee_profile', None),
            'employment_status',
            EmployeeProfile.EmploymentStatus.ACTIVE,
        )
        self._normalize_profile_status(validated_data, profile_data, current_status=current_status)
        self._validate_compensation_data(compensation_data)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        password = self.context['request'].data.get('password')
        pin = self.context['request'].data.get('pin')
        if password:
            instance.set_password(password)
        if pin:
            instance.set_pin(pin)
        instance.save()
        if allowed_halls is not None:
            instance.allowed_halls.set(allowed_halls)
        self._save_profile(instance, profile_data)
        self._save_compensation(instance, compensation_data)
        instance.refresh_from_db()
        return instance
