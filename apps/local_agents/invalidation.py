import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from apps.local_agents.models import LocalAgent
from apps.local_agents.services import local_agent_group_name


logger = logging.getLogger(__name__)


def broadcast_operational_invalidation(*, restaurant_id) -> bool:
    """Wake the restaurant Agent after a direct backend POS mutation.

    Delivery is intentionally best-effort.  The Agent also performs periodic
    operational reconciliation, so a lost websocket event cannot create a
    permanent cache gap.
    """

    agent_ids = list(
        LocalAgent.objects.filter(restaurant_id=restaurant_id, is_active=True)
        .values_list('id', flat=True)
    )
    if not agent_ids:
        return False
    channel_layer = get_channel_layer()
    event = {
        'type': 'operational.invalidate',
        'server_time': timezone.now().isoformat(),
    }
    delivered = False
    for agent_id in agent_ids:
        try:
            async_to_sync(channel_layer.group_send)(
                local_agent_group_name(agent_id), event
            )
            delivered = True
        except Exception:
            logger.exception(
                'Local Agent operational invalidation could not be delivered.',
                extra={
                    'restaurant_id': str(restaurant_id),
                    'local_agent_id': str(agent_id),
                },
            )
    return delivered
