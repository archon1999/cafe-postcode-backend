from django.contrib import admin

from .models import EmployeeProfile, Permission, PermissionEndpoint, RestaurantProfile, Role, User


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name')
    search_fields = ('code', 'name')


@admin.register(PermissionEndpoint)
class PermissionEndpointAdmin(admin.ModelAdmin):
    list_display = ('method', 'url', 'permission')
    list_filter = ('method',)
    search_fields = ('url', 'permission__code', 'permission__name')


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'is_system')
    search_fields = ('code', 'name')
    filter_horizontal = ('permissions',)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'full_name', 'role', 'is_active', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'role')
    search_fields = ('username', 'full_name', 'phone')
    filter_horizontal = ('groups', 'user_permissions')


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'employment_status', 'salary_type')
    list_filter = ('employment_status', 'salary_type')
    search_fields = ('user__username', 'user__full_name')


@admin.register(RestaurantProfile)
class RestaurantProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'restaurant', 'primary_hall', 'hall_switch_permission')
    search_fields = ('user__username', 'restaurant__name')
    filter_horizontal = ('allowed_halls',)
