from django.urls import path

from .views import (
    PosMenuView,
)

urlpatterns = [
    path('pos/catalog/menu/', PosMenuView.as_view()),
]
