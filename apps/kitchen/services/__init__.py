from .order_ticket_sync import OrderTicketSyncService


def sync_order_tickets(order):
    OrderTicketSyncService().sync(order=order)

