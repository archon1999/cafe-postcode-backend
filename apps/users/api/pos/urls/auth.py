from django.urls import path

from apps.users.api.pos.views.auth import LogoutView, PosMeView, PosPinLoginView, PosRestaurantCodeView

urlpatterns = [
    path('restaurant-code/', PosRestaurantCodeView.as_view()),
    path('pin-login/', PosPinLoginView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('me/', PosMeView.as_view()),
]
