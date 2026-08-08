from apps.kitchen.models import KitchenAnnouncement, KitchenTicket


def create_ready_announcement(*, order):
    display_name = (order.display_name or str(order.order_number)).strip()
    announcement, _created = KitchenAnnouncement.objects.get_or_create(
        order=order,
        kind=KitchenAnnouncement.Kind.AUTO,
        defaults={
            'restaurant': order.restaurant,
            'display_name': display_name,
            'locale': KitchenAnnouncement.Locale.UZ,
        },
    )
    return announcement


def create_replay_announcement(*, ticket: KitchenTicket, user):
    order = ticket.order
    display_name = (order.display_name or str(order.order_number)).strip()
    return KitchenAnnouncement.objects.create(
        restaurant=ticket.restaurant,
        order=order,
        display_name=display_name,
        locale=KitchenAnnouncement.Locale.UZ,
        kind=KitchenAnnouncement.Kind.REPLAY,
        created_by=user,
    )
