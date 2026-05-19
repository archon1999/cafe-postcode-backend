from django.urls import path

from apps.catalog.api.pos.views.menu import PosMenuView
from apps.catalog.api.pos.views.scan import PosCatalogScanView

urlpatterns = [
    path('menu/', PosMenuView.as_view()),
    path('scan/', PosCatalogScanView.as_view()),
]
