from django.apps import apps


def get_business_partner_model():
    return apps.get_model('platform', 'BusinessPartner')


def get_restaurant_entitlement_model():
    return apps.get_model('platform', 'RestaurantEntitlement')


def get_tariff_model():
    return apps.get_model('platform', 'Tariff')
