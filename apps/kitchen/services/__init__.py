from .closed_order_cleanup import complete_stale_closed_order_kitchen_work
from .kitchen_announcements import create_ready_announcement, create_replay_announcement
from .order_ticket_sync import OrderTicketSyncService
from .tv_monitor_pairing import (
    authenticate_tv_monitor_device,
    claim_tv_monitor_pairing,
    create_tv_monitor_pairing,
    get_tv_monitor_pairing,
)


def sync_order_tickets(order):
    OrderTicketSyncService().sync(order=order)


def dispatch_order_tickets(
    order,
    *,
    created_by=None,
    order_item_ids=None,
    create_sale_print_documents=True,
):
    return OrderTicketSyncService().dispatch(
        order=order,
        created_by=created_by,
        order_item_ids=order_item_ids,
        create_sale_print_documents=create_sale_print_documents,
    )


__all__ = [
    'OrderTicketSyncService',
    'authenticate_tv_monitor_device',
    'claim_tv_monitor_pairing',
    'complete_stale_closed_order_kitchen_work',
    'create_ready_announcement',
    'create_replay_announcement',
    'create_tv_monitor_pairing',
    'dispatch_order_tickets',
    'get_tv_monitor_pairing',
    'sync_order_tickets',
]
