from django.urls import path

from apps.floor.api.pos.views import (
    DiningTableReserveView,
    PosHallListView,
    TableSessionDetailView,
    TableSessionListCreateView,
    TableSessionMergeView,
    TableSessionMoveView,
    TableSessionGroupView,
    TableSessionTransferView,
    TableSessionUngroupView,
)

urlpatterns = [
    path('halls/', PosHallListView.as_view()),
    path('tables/<uuid:pk>/reserve/', DiningTableReserveView.as_view()),
    path('table-sessions/', TableSessionListCreateView.as_view()),
    path('table-sessions/<uuid:pk>/', TableSessionDetailView.as_view()),
    path('table-sessions/<uuid:pk>/move/', TableSessionMoveView.as_view()),
    path('table-sessions/<uuid:pk>/merge/', TableSessionMergeView.as_view()),
    path('table-sessions/<uuid:pk>/transfer/', TableSessionTransferView.as_view()),
    path('table-sessions/<uuid:pk>/group/', TableSessionGroupView.as_view()),
    path('table-sessions/<uuid:pk>/ungroup/', TableSessionUngroupView.as_view()),
]
