from django.urls import path

from apps.admin.views import (
    BusinessPartnerActivateView,
    BusinessPartnerDeactivateView,
    BusinessPartnerDetailView,
    BusinessPartnerListCreateView,
    BusinessPartnerResetPasswordView,
    RestaurantActivateView,
    RestaurantDeactivateView,
    RestaurantResetPasswordView,
    TariffDetailView,
    TariffListCreateView,
)

urlpatterns = [
    path('platform/business-partners/', BusinessPartnerListCreateView.as_view()),
    path('platform/business-partners/<uuid:pk>/', BusinessPartnerDetailView.as_view()),
    path('platform/business-partners/<uuid:pk>/activate/', BusinessPartnerActivateView.as_view()),
    path('platform/business-partners/<uuid:pk>/deactivate/', BusinessPartnerDeactivateView.as_view()),
    path('platform/business-partners/<uuid:pk>/reset-password/', BusinessPartnerResetPasswordView.as_view()),
    path('platform/tariffs/', TariffListCreateView.as_view()),
    path('platform/tariffs/<uuid:pk>/', TariffDetailView.as_view()),
    path('platform/restaurants/<uuid:pk>/activate/', RestaurantActivateView.as_view()),
    path('platform/restaurants/<uuid:pk>/deactivate/', RestaurantDeactivateView.as_view()),
    path('platform/restaurants/<uuid:pk>/reset-password/', RestaurantResetPasswordView.as_view()),
]
