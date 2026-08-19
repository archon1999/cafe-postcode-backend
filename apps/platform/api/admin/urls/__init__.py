from django.urls import path

from apps.platform.api.admin.views.business_partners import (
    BusinessPartnerActivateView,
    BusinessPartnerActivationDefaultsView,
    BusinessPartnerDeactivateView,
    BusinessPartnerDetailView,
    BusinessPartnerListCreateView,
    BusinessPartnerLookupView,
    BusinessPartnerResetPasswordView,
)
from apps.platform.api.admin.views.restaurants import (
    RestaurantActivateView,
    RestaurantActivationOptionsView,
    RestaurantDeactivateView,
    RestaurantResetPasswordView,
    RestaurantTariffChangeView,
)
from apps.platform.api.admin.views.tariffs import TariffDetailView, TariffListCreateView, TariffOptionsView

urlpatterns = [
    path('business-partners/', BusinessPartnerListCreateView.as_view()),
    path('business-partners/lookup/', BusinessPartnerLookupView.as_view()),
    path('business-partners/<uuid:pk>/', BusinessPartnerDetailView.as_view()),
    path('business-partners/<uuid:pk>/activation-defaults/', BusinessPartnerActivationDefaultsView.as_view()),
    path('business-partners/<uuid:pk>/activate/', BusinessPartnerActivateView.as_view()),
    path('business-partners/<uuid:pk>/deactivate/', BusinessPartnerDeactivateView.as_view()),
    path('business-partners/<uuid:pk>/reset-password/', BusinessPartnerResetPasswordView.as_view()),
    path('tariff-options/', TariffOptionsView.as_view()),
    path('tariffs/', TariffListCreateView.as_view()),
    path('tariffs/<uuid:pk>/', TariffDetailView.as_view()),
    path('restaurants/activation-options/', RestaurantActivationOptionsView.as_view()),
    path('restaurants/<uuid:pk>/activate/', RestaurantActivateView.as_view()),
    path('restaurants/<uuid:pk>/deactivate/', RestaurantDeactivateView.as_view()),
    path('restaurants/<uuid:pk>/tariff-change/', RestaurantTariffChangeView.as_view()),
    path('restaurants/<uuid:pk>/reset-password/', RestaurantResetPasswordView.as_view()),
]
