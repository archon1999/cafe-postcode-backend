from django.urls import path

from apps.users.api.pos.views.auth import (
    LogoutView,
    LegacyRestaurantCodeView,
    PosLockView,
    PosMeView,
    PosPinLoginView,
    PosTransportDiscoveryView,
    PosDeviceTransportDiscoveryView,
    PosUnlockView,
)

urlpatterns = [
    path('restaurant-code/', LegacyRestaurantCodeView.as_view()),
    path('transport/', PosTransportDiscoveryView.as_view()),
    path('device-transport/', PosDeviceTransportDiscoveryView.as_view()),
    path('pin-login/', PosPinLoginView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('lock/', PosLockView.as_view()),
    path('unlock/', PosUnlockView.as_view()),
    path('me/', PosMeView.as_view()),
]
