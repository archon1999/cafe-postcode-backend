from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from common.models import BaseModel

from .permission import Permission
from .user_manager import UserManager


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    ADMIN_PERMISSION_CODES = {
        'partners.view',
        'partners.manage',
        'tariffs.view',
        'tariffs.manage',
        'restaurants.view',
        'restaurants.manage',
        'restaurants.activate',
        'restaurants.deactivate',
        'restaurants.reset_password',
        'reports.view',
        'orders.view',
        'orders.manage',
        'payments.view',
        'payments.manage',
        'payments.create',
        'kitchen.view',
        'kitchen.update',
        'kitchen.manage',
        'catalog.view',
        'catalog.manage',
        'hall.view',
        'hall.manage',
        'table.manage',
        'users.manage',
        'permissions.view',
        'roles.view',
        'integrations.manage',
        'cashdesk.manage',
    }
    POS_PERMISSION_CODES = {
        'hall.view',
        'hall.manage',
        'table.manage',
        'orders.create',
        'orders.view',
        'orders.manage',
        'payments.create',
        'payments.view',
        'payments.manage',
        'cashshift.view',
        'cashshift.open',
        'cashshift.close',
        'receipt.reprint',
        'payment.refund',
        'kitchen.view',
        'kitchen.update',
        'kitchen.manage',
        'stoplist.manage',
    }

    class ActorType(models.TextChoices):
        PRODUCT_OWNER = 'product_owner', 'Product owner'
        BUSINESS_PARTNER = 'business_partner', 'Business partner'
        RESTAURANT_ADMIN = 'restaurant_admin', 'Restaurant admin'
        RESTAURANT_STAFF = 'restaurant_staff', 'Restaurant staff'

    class UiMode(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        POS = 'pos', 'POS'

    restaurant = models.ForeignKey(
        'organizations.Restaurant',
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True,
    )
    branch = models.ForeignKey(
        'organizations.Branch',
        on_delete=models.SET_NULL,
        related_name='users',
        null=True,
        blank=True,
    )
    business_partner = models.ForeignKey(
        'organizations.BusinessPartner',
        on_delete=models.SET_NULL,
        related_name='users',
        null=True,
        blank=True,
    )
    role = models.ForeignKey('accounts.Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=30, blank=True, default='')
    pin_code = models.CharField(max_length=128, blank=True, default='')
    actor_type = models.CharField(max_length=30, choices=ActorType.choices, default=ActorType.RESTAURANT_STAFF)
    ui_mode = models.CharField(max_length=20, choices=UiMode.choices, default=UiMode.POS)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    hall_switch_permission = models.BooleanField(default=False)
    primary_hall = models.ForeignKey(
        'floor.Hall',
        on_delete=models.SET_NULL,
        related_name='primary_users',
        null=True,
        blank=True,
    )
    allowed_halls = models.ManyToManyField('floor.Hall', blank=True, related_name='allowed_users')

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['full_name']

    objects = UserManager()

    class Meta:
        ordering = ('username',)

    def __str__(self):
        return self.username

    def get_restaurant_profile(self):
        return getattr(self, 'restaurant_profile', None)

    def get_business_partner_profile(self):
        return getattr(self, 'business_partner_profile', None)

    def get_restaurant_scope(self):
        profile = self.get_restaurant_profile()
        if profile and profile.restaurant_id:
            return profile.restaurant
        return self.restaurant

    def get_business_partner_scope(self):
        profile = self.get_business_partner_profile()
        if profile and profile.business_partner_id:
            return profile.business_partner
        return self.business_partner

    def set_pin(self, raw_pin: str):
        profile = self.get_restaurant_profile()
        if profile is None:
            raise ValueError('Restaurant user profile is required to manage PIN codes.')
        profile.pin_code = make_password(raw_pin)
        profile.save(update_fields=['pin_code'])

    def check_pin(self, raw_pin: str) -> bool:
        profile = self.get_restaurant_profile()
        if profile is None or not profile.pin_code:
            return False
        return check_password(raw_pin, profile.pin_code)

    @property
    def permission_codes(self):
        if self.is_superuser:
            return list(Permission.objects.values_list('code', flat=True))
        role_permission_codes = set(self.role.permissions.values_list('code', flat=True)) if self.role_id else set()
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

        return sorted(role_permission_codes)

    def has_permission_code(self, code: str) -> bool:
        if self.is_superuser:
            return True
        return code in self.permission_codes

    @property
    def restaurant_access_active(self) -> bool:
        if self.is_superuser:
            return True

        restaurant = self.get_restaurant_scope()
        if restaurant is None:
            return self.is_active

        if not getattr(restaurant, 'is_active', False):
            return False

        entitlement = getattr(restaurant, 'entitlement', None)
        return bool(self.is_active and entitlement and entitlement.is_active)

    @property
    def can_access_admin_ui(self) -> bool:
        if self.is_superuser:
            return True
        return bool(set(self.permission_codes) & self.ADMIN_PERMISSION_CODES)

    @property
    def can_access_pos_ui(self) -> bool:
        if self.is_superuser:
            return True
        return bool(self.get_restaurant_scope() and set(self.permission_codes) & self.POS_PERMISSION_CODES)
