from apps.devices.models import Device


def pos_device_state_snapshot(*, restaurant) -> list[dict]:
    """Return the complete POS device authority set for one Agent restaurant."""
    devices = (
        Device.objects.filter(restaurant=restaurant, type=Device.Type.POS_TERMINAL)
        .only('id', 'status', 'revoked_at', 'updated_at')
        .order_by('created_at', 'id')
    )
    return [
        {
            'backendDeviceId': str(device.id),
            'status': (
                Device.Status.ACTIVE
                if device.status == Device.Status.ACTIVE and device.revoked_at is None
                else Device.Status.REVOKED
            ),
            'revokedAt': (
                None
                if device.status == Device.Status.ACTIVE and device.revoked_at is None
                else (device.revoked_at or device.updated_at).isoformat()
            ),
        }
        for device in devices
    ]
