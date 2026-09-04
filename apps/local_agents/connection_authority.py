import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qsl

from django.db import transaction
from django.utils import timezone

from apps.local_agents.models import LocalAgent, LocalAgentConnection


AUTHORITY_LIVENESS_SECONDS = 75
DOWNGRADE_HOLDOFF_SECONDS = 90
VERSION_RE = re.compile(
    r'^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)'
    r'(?P<suffix>[-+][0-9A-Za-z.-]+)?$'
)
INSTANCE_RE = re.compile(r'^[A-Za-z0-9_-]{22,128}$')
ALLOWED_QUERY_KEYS = frozenset({'agentVersion', 'instanceId', 'protocolVersion'})


@dataclass(frozen=True)
class ConnectionIdentity:
    version: str = ''
    runtime_instance_id: str = ''
    protocol_version: int = 1
    attested: bool = False


@dataclass(frozen=True)
class AuthorityClaim:
    accepted: bool
    displaced_channel_name: str = ''
    reason: str = ''


def _version_rank(value: str):
    match = VERSION_RE.fullmatch(str(value or ''))
    if match is None:
        return None
    suffix = match.group('suffix') or ''
    # A final build wins over a prerelease with the same numeric version.
    final_rank = 1 if not suffix or suffix.startswith('+') else 0
    return (
        int(match.group('major')),
        int(match.group('minor')),
        int(match.group('patch')),
        final_rank,
        suffix,
    )


def connection_identity_from_scope(scope, *, device_authenticated: bool):
    raw_query = scope.get('query_string', b'') or b''
    try:
        pairs = parse_qsl(raw_query.decode('ascii'), keep_blank_values=True)
    except (UnicodeDecodeError, ValueError):
        return None
    if not pairs:
        return ConnectionIdentity()
    if any(key not in ALLOWED_QUERY_KEYS for key, _value in pairs):
        return None
    values = {}
    for key, value in pairs:
        if key in values:
            return None
        values[key] = value
    if set(values) != ALLOWED_QUERY_KEYS or not device_authenticated:
        return None
    version = values['agentVersion']
    instance_id = values['instanceId']
    if _version_rank(version) is None or not INSTANCE_RE.fullmatch(instance_id):
        return None
    try:
        protocol_version = int(values['protocolVersion'])
    except ValueError:
        return None
    if str(protocol_version) != values['protocolVersion'] or not 1 <= protocol_version <= 255:
        return None
    return ConnectionIdentity(
        version=version,
        runtime_instance_id=instance_id,
        protocol_version=protocol_version,
        attested=True,
    )


def claim_connection_authority(
    *,
    agent_id,
    connection_id: uuid.UUID,
    channel_name: str,
    identity: ConnectionIdentity,
    now=None,
) -> AuthorityClaim:
    now = now or timezone.now()
    with transaction.atomic():
        agent = LocalAgent.objects.select_for_update().get(pk=agent_id)
        lease, _created = LocalAgentConnection.objects.get_or_create(agent=agent)
        previous_channel = lease.channel_name if lease.connected else ''
        current_fresh = bool(
            lease.connected
            and lease.last_seen_at
            and lease.last_seen_at >= now - timedelta(seconds=AUTHORITY_LIVENESS_SECONDS)
        )
        preference_fresh = bool(
            lease.last_seen_at
            and lease.last_seen_at >= now - timedelta(seconds=DOWNGRADE_HOLDOFF_SECONDS)
        )
        same_instance = bool(
            identity.attested
            and lease.identity_attested
            and identity.runtime_instance_id == lease.runtime_instance_id
        )
        candidate_rank = _version_rank(identity.version) if identity.attested else None
        current_rank = _version_rank(lease.version) if lease.identity_attested else None
        newer_attested = bool(
            identity.attested
            and (
                not lease.identity_attested
                or current_rank is None
                or candidate_rank > current_rank
            )
        )

        accepted = False
        reason = ''
        if lease.connection_id is None and lease.last_seen_at is None:
            accepted = True
        elif current_fresh:
            accepted = same_instance or newer_attested
            if not accepted:
                reason = 'another authoritative Local Agent socket is active'
        elif not lease.identity_attested:
            # Old clients do not carry a signed runtime identity. Once their
            # socket is gone, preserve pre-upgrade reconnect behavior.
            accepted = True
        elif identity.attested and candidate_rank is not None and current_rank is not None and candidate_rank >= current_rank:
            accepted = True
        elif not preference_fresh:
            # A real updater rollback must eventually recover even when the
            # prior higher-version process died without a clean disconnect.
            accepted = True
        else:
            reason = 'a newer Local Agent connection is preferred during rollback holdoff'

        if not accepted:
            return AuthorityClaim(accepted=False, reason=reason)

        lease.connection_id = connection_id
        lease.runtime_instance_id = identity.runtime_instance_id
        lease.version = identity.version
        lease.protocol_version = identity.protocol_version
        lease.identity_attested = identity.attested
        lease.channel_name = channel_name
        lease.connected = True
        lease.connected_at = now
        lease.last_seen_at = now
        lease.save()
        return AuthorityClaim(
            accepted=True,
            displaced_channel_name=(
                previous_channel if previous_channel and previous_channel != channel_name else ''
            ),
        )


def is_connection_authority(*, agent_id, connection_id) -> bool:
    return LocalAgentConnection.objects.filter(
        agent_id=agent_id,
        connection_id=connection_id,
        connected=True,
    ).exists()


def release_connection_authority(*, agent_id, connection_id, now=None) -> bool:
    now = now or timezone.now()
    with transaction.atomic():
        agent = LocalAgent.objects.select_for_update().get(pk=agent_id)
        lease = LocalAgentConnection.objects.select_for_update().filter(agent=agent).first()
        if lease is None or lease.connection_id != connection_id or not lease.connected:
            return False
        lease.connection_id = None
        lease.channel_name = ''
        lease.connected = False
        lease.last_seen_at = now
        lease.save(
            update_fields=[
                'connection_id',
                'channel_name',
                'connected',
                'last_seen_at',
                'updated_at',
            ]
        )
        LocalAgent.objects.filter(pk=agent.pk).update(
            status=LocalAgent.Status.OFFLINE,
            updated_at=now,
        )
        return True
