from django.urls import path

from apps.catalog.api.pos.views.menu import PosMenuView

urlpatterns = [
    path('menu/', PosMenuView.as_view()),
]
