from django.urls import path

from .views import (
    CashDeskDetailView,
    CashDeskListCreateView,
    DistributionPointDetailView,
    DistributionPointListCreateView,
    FeatureConfigView,
    PrepStationDetailView,
    PrepStationListCreateView,
    RestaurantConfigView,
)

urlpatterns = [
    path('admin/constructor/restaurant/', RestaurantConfigView.as_view()),
    path('admin/constructor/features/', FeatureConfigView.as_view()),
    path('admin/constructor/prep-stations/', PrepStationListCreateView.as_view()),
    path('admin/constructor/prep-stations/<uuid:pk>/', PrepStationDetailView.as_view()),
    path('admin/constructor/cash-desks/', CashDeskListCreateView.as_view()),
    path('admin/constructor/cash-desks/<uuid:pk>/', CashDeskDetailView.as_view()),
    path('admin/constructor/distribution-points/', DistributionPointListCreateView.as_view()),
    path('admin/constructor/distribution-points/<uuid:pk>/', DistributionPointDetailView.as_view()),
]
