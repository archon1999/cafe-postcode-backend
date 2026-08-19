from django.contrib import admin

from apps.devices.models import Device, DevicePairing, SecurityEvent


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'restaurant', 'status', 'lease_expires_at', 'last_seen_at')
    list_filter = ('type', 'status')
    search_fields = ('name', 'restaurant__name', 'public_key_fingerprint')
    readonly_fields = ('public_key_fingerprint', 'paired_at', 'revoked_at', 'created_at', 'updated_at')


@admin.register(DevicePairing)
class DevicePairingAdmin(admin.ModelAdmin):
    list_display = ('requested_name', 'device_type', 'status', 'display_code', 'expires_at', 'created_at')
    list_filter = ('device_type', 'status')
    search_fields = ('requested_name', 'public_key_fingerprint')


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'severity', 'restaurant', 'device', 'result', 'created_at')
    list_filter = ('severity', 'event_type', 'result')
    search_fields = ('event_type', 'restaurant__name', 'request_id')
    readonly_fields = tuple(field.name for field in SecurityEvent._meta.fields)
