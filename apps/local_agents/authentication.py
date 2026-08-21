import hmac

from django.conf import settings
from django.db import transaction

from common.api.client_ip import get_client_ip
from apps.devices.authentication import authenticate_device_request
from apps.devices.migration_window import legacy_cohort_eligible, legacy_local_agent_auth_enabled
from apps.devices.models import Device
from apps.local_agents.models import LocalAgent, hash_agent_token


def _recover_bounded_legacy_token(request, token):
    """Bind one explicitly allowlisted legacy install during the incident window.

    Entries are ``client-ip=restaurant-uuid``.  The raw bearer is never logged
    or persisted; only its normal verifier hash replaces the already-lost
    legacy verifier.  Removing the environment entry disables recovery.
    """
    raw_bindings = str(getattr(settings, 'DEVICE_LEGACY_LOCAL_AGENT_RECOVERY_BINDINGS', '') or '')
    client_ip = str(get_client_ip(request) or '')
    restaurant_id = ''
    for entry in raw_bindings.split(','):
        configured_ip, separator, configured_restaurant = entry.strip().partition('=')
        if separator and hmac.compare_digest(configured_ip, client_ip):
            restaurant_id = configured_restaurant.strip()
            break
    if not restaurant_id or not token.startswith('cpa_'):
        return None

    with transaction.atomic():
        agent = (
            LocalAgent.objects.select_for_update()
            .filter(restaurant_id=restaurant_id, is_active=True)
            .first()
        )
        if (
            agent is None
            or agent.device_id is not None
            or agent.credential_migrated_at is not None
            or not legacy_cohort_eligible(created_at=agent.created_at)
        ):
            return None
        agent.token_hash = hash_agent_token(token)
        agent.save(update_fields=['token_hash', 'updated_at'])
        return agent


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
    if agent is None and token:
        agent = _recover_bounded_legacy_token(request, token)
    if agent is None or not legacy_cohort_eligible(created_at=agent.created_at):
        return None
    return agent
