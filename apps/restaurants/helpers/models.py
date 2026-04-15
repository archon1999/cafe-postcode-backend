from django.apps import apps


def get_cash_desk_model():
    return apps.get_model('restaurants', 'CashDesk')


def get_distribution_point_model():
    return apps.get_model('restaurants', 'DistributionPoint')


def get_prep_station_model():
    return apps.get_model('restaurants', 'PrepStation')


def get_restaurant_model():
    return apps.get_model('restaurants', 'Restaurant')
