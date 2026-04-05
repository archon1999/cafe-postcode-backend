from django.urls import path

from apps.floor.api.admin.views.halls import HallConstructorView, HallDetailView, HallListCreateView
from apps.floor.api.admin.views.table_sessions import TableSessionDetailView, TableSessionListCreateView
from apps.floor.api.admin.views.tables import DiningTableDetailView, DiningTableListCreateView
from apps.floor.api.admin.views.zones import ZoneDetailView, ZoneListCreateView

urlpatterns = [
    path('halls/', HallListCreateView.as_view()),
    path('halls/<uuid:pk>/', HallDetailView.as_view()),
    path('halls/<uuid:pk>/constructor/', HallConstructorView.as_view()),
    path('zones/', ZoneListCreateView.as_view()),
    path('zones/<uuid:pk>/', ZoneDetailView.as_view()),
    path('tables/', DiningTableListCreateView.as_view()),
    path('tables/<uuid:pk>/', DiningTableDetailView.as_view()),
    path('table-sessions/', TableSessionListCreateView.as_view()),
    path('table-sessions/<uuid:pk>/', TableSessionDetailView.as_view()),
]
