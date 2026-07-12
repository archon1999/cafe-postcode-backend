from django.urls import path

from apps.restaurants.api.admin.views.cash_desks import CashDeskDetailView, CashDeskListCreateView
from apps.restaurants.api.admin.views.distribution_points import (
    DistributionPointDetailView,
    DistributionPointListCreateView,
)
from apps.restaurants.api.admin.views.my_restaurant import MyRestaurantDetailView, RestaurantConfigView
from apps.restaurants.api.admin.views.prep_stations import PrepStationDetailView, PrepStationListCreateView
from apps.restaurants.api.admin.views.restaurants import (
    RestaurantDetailView,
    RestaurantListCreateView,
    RestaurantLookupView,
    RestaurantReadDetailView,
)
from apps.restaurants.api.admin.views.setup import RestaurantSetupApplyView, RestaurantSetupReadinessView

urlpatterns = [
    path('setup/readiness/', RestaurantSetupReadinessView.as_view()),
    path('setup/apply/', RestaurantSetupApplyView.as_view()),
    path('settings/', RestaurantConfigView.as_view()),
    path('my-restaurant/', MyRestaurantDetailView.as_view()),
    path('lookup/', RestaurantLookupView.as_view()),
    path('prep-stations/', PrepStationListCreateView.as_view()),
    path('prep-stations/<uuid:pk>/', PrepStationDetailView.as_view()),
    path('cash-desks/', CashDeskListCreateView.as_view()),
    path('cash-desks/<uuid:pk>/', CashDeskDetailView.as_view()),
    path('distribution-points/', DistributionPointListCreateView.as_view()),
    path('distribution-points/<uuid:pk>/', DistributionPointDetailView.as_view()),
    path('', RestaurantListCreateView.as_view()),
    path('<uuid:pk>/detail/', RestaurantReadDetailView.as_view()),
    path('<uuid:pk>/', RestaurantDetailView.as_view()),
]
