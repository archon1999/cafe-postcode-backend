from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from apps.users.permission_registry import ADMIN_UI_PERMISSION_CODES, POS_UI_PERMISSION_CODES
from common.models import BaseModel

from .permission import Permission


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('The given username must be set')

        restaurant = extra_fields.pop('restaurant', None)
        business_partner = extra_fields.pop('business_partner', None)

        user = self.model(username=username, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)

        if restaurant is not None:
            from apps.users.models.restaurant_profile import RestaurantProfile

            RestaurantProfile.objects.update_or_create(
                user=user,
                defaults={'restaurant': restaurant},
            )

        if business_partner is not None:
            business_partner.owner_user = user
            business_partner.save(update_fields=['owner_user', 'updated_at'])

        return user

    def create_user(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(username, password, **extra_fields)

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    role = models.ForeignKey('users.Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=30, blank=True, default='')
    pin_code = models.CharField(max_length=128, blank=True, default='')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['full_name']

    objects = UserManager()

    class Meta:
        ordering = ('username',)

    def __str__(self):
        return self.username

    def _get_optional_relation(self, relation_name: str):
        try:
            return getattr(self, relation_name)
        except ObjectDoesNotExist:
            return None

    @property
    def role_code(self) -> str | None:
        return getattr(self.role, 'code', None)

    def get_restaurant_scope(self):
        profile = self._get_optional_relation('restaurant_profile')
        if profile and profile.restaurant_id:
            return profile.restaurant
        return None

    def get_business_partner_scope(self):
        business_partner = self._get_optional_relation('business_partner_profile')
        if business_partner and business_partner.pk:
            return business_partner
        return None

    def set_pin(self, raw_pin: str):
        hashed_pin = make_password(raw_pin)
        self.pin_code = hashed_pin
        profile = self._get_optional_relation('restaurant_profile')
        if profile is not None:
            profile.pin_code = hashed_pin
            profile.save(update_fields=['pin_code'])

    def check_pin(self, raw_pin: str) -> bool:
        profile = self._get_optional_relation('restaurant_profile')
        if profile is not None and profile.pin_code and check_password(raw_pin, profile.pin_code):
            return True
        if not self.pin_code:
            return False
        return check_password(raw_pin, self.pin_code)

    @property
    def permission_codes(self):
        if self.is_superuser:
            return list(Permission.objects.values_list('code', flat=True))

        role_permission_codes = (
            {permission.code for permission in self.role.permissions.all()}
            if self.role_id
            else set()
        )
        if not role_permission_codes:
            return []

        restaurant = self.get_restaurant_scope()
        if restaurant is not None:
            if not getattr(restaurant, 'is_active', False):
                return []
            entitlement = getattr(restaurant, 'entitlement', None)
            if entitlement is None or not entitlement.is_active:
                return []
            return sorted(role_permission_codes & entitlement.get_effective_permission_codes())

        business_partner = self.get_business_partner_scope()
        if business_partner is not None:
            if getattr(business_partner, 'status', None) != 'active':
                return []
            extra_permission_codes = set(business_partner.extra_permissions.values_list('code', flat=True))
            return sorted(role_permission_codes | extra_permission_codes)

        return sorted(role_permission_codes)

    @property
    def restaurant_access_active(self) -> bool:
        if self.is_superuser:
            return True

        restaurant = self.get_restaurant_scope()
        if restaurant is None:
            business_partner = self.get_business_partner_scope()
            if business_partner is not None:
                return bool(self.is_active and getattr(business_partner, 'status', None) == 'active')
            return self.is_active

        if not getattr(restaurant, 'is_active', False):
            return False

        entitlement = getattr(restaurant, 'entitlement', None)
        return bool(self.is_active and entitlement and entitlement.is_active)

    @property
    def can_access_admin_ui(self) -> bool:
        if self.is_superuser:
            return True
        return bool(set(self.permission_codes) & ADMIN_UI_PERMISSION_CODES)

    @property
    def can_access_pos_ui(self) -> bool:
        if self.is_superuser:
            return True
        return bool(self.get_restaurant_scope() and set(self.permission_codes) & POS_UI_PERMISSION_CODES)
