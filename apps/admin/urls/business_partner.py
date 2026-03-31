from django.urls import path

from apps.admin.views import (
    RestaurantActivateView,
    RestaurantDeactivateView,
    RestaurantResetPasswordView,
)

urlpatterns = [
    path('platform/restaurants/<uuid:pk>/activate/', RestaurantActivateView.as_view()),
    path('platform/restaurants/<uuid:pk>/deactivate/', RestaurantDeactivateView.as_view()),
    path('platform/restaurants/<uuid:pk>/reset-password/', RestaurantResetPasswordView.as_view()),
]
