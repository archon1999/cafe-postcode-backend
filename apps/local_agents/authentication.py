from apps.devices.authentication import authenticate_device_request
from apps.devices.migration_window import legacy_cohort_eligible, legacy_local_agent_auth_enabled
from apps.devices.models import Device
from apps.local_agents.models import LocalAgent


def authenticate_local_agent(request):
    if request.headers.get('X-Device-Id'):
        device = authenticate_device_request(request, expected_types=[Device.Type.LOCAL_AGENT])
        return LocalAgent.objects.select_related('restaurant', 'device').filter(
            device=device,
            restaurant=device.restaurant,
            is_active=True,
        ).first()
    if not legacy_local_agent_auth_enabled():
        return None
    token = str(request.headers.get('Authorization', '')).removeprefix('Bearer ').strip()
    # The bounded incident/migration window must also let an older duplicate
    # installation finish sync and receive its signed update after another
    # copy already marked the server credential as migrated. Outside that
    # window this entire bearer path remains disabled.
    agent = LocalAgent.authenticate_token(token, allow_migrated=True) if token else None
    if agent is None or not legacy_cohort_eligible(created_at=agent.created_at):
        return None
    return agent
