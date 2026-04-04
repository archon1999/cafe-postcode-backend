from django.urls import path

from apps.admin.views import (
    BusinessPartnerActivateView,
    BusinessPartnerDeactivateView,
    BusinessPartnerDetailView,
    BusinessPartnerListCreateView,
    BusinessPartnerLookupView,
    BusinessPartnerResetPasswordView,
    TariffDetailView,
    TariffListCreateView,
    TariffOptionsView,
)

urlpatterns = [
    path('platform/business-partners/', BusinessPartnerListCreateView.as_view()),
    path('platform/business-partners/lookup/', BusinessPartnerLookupView.as_view()),
    path('platform/business-partners/<uuid:pk>/', BusinessPartnerDetailView.as_view()),
    path('platform/business-partners/<uuid:pk>/activate/', BusinessPartnerActivateView.as_view()),
    path('platform/business-partners/<uuid:pk>/deactivate/', BusinessPartnerDeactivateView.as_view()),
    path('platform/business-partners/<uuid:pk>/reset-password/', BusinessPartnerResetPasswordView.as_view()),
    path('platform/tariff-options/', TariffOptionsView.as_view()),
    path('platform/tariffs/', TariffListCreateView.as_view()),
    path('platform/tariffs/<uuid:pk>/', TariffDetailView.as_view()),
]
