from django.urls import path

from .views import (
    LogoutView,
    PosMeView,
    PosPinLoginView,
    PosRestaurantCodeView,
)

urlpatterns = [
    path('pos/auth/restaurant-code/', PosRestaurantCodeView.as_view()),
    path('pos/auth/pin-login/', PosPinLoginView.as_view()),
    path('pos/auth/logout/', LogoutView.as_view()),
    path('pos/auth/me/', PosMeView.as_view()),
]
