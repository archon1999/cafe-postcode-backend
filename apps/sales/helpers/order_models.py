from django.apps import apps


def get_order_model():
    return apps.get_model('sales', 'Order')


def get_order_item_model():
    return apps.get_model('sales', 'OrderItem')


def get_order_item_note_model():
    return apps.get_model('sales', 'OrderItemNote')
