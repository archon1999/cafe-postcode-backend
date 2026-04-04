from django.urls import path

from apps.admin.views import (
    RestaurantActivateView,
    RestaurantActivationOptionsView,
    RestaurantDeactivateView,
    RestaurantRotateAuthCodeView,
    RestaurantResetPasswordView,
)

urlpatterns = [
    path('platform/restaurants/activation-options/', RestaurantActivationOptionsView.as_view()),
    path('platform/restaurants/<uuid:pk>/activate/', RestaurantActivateView.as_view()),
    path('platform/restaurants/<uuid:pk>/deactivate/', RestaurantDeactivateView.as_view()),
    path('platform/restaurants/<uuid:pk>/rotate-auth-code/', RestaurantRotateAuthCodeView.as_view()),
    path('platform/restaurants/<uuid:pk>/reset-password/', RestaurantResetPasswordView.as_view()),
]
