from django.urls import path

from .views import (
    PosHallListView,
    TableSessionDetailView,
    TableSessionListCreateView,
    TableSessionMergeView,
    TableSessionMoveView,
)

urlpatterns = [
    path('pos/halls/', PosHallListView.as_view()),
    path('pos/halls/table-sessions/', TableSessionListCreateView.as_view()),
    path('pos/halls/table-sessions/<uuid:pk>/', TableSessionDetailView.as_view()),
    path('pos/halls/table-sessions/<uuid:pk>/move/', TableSessionMoveView.as_view()),
    path('pos/halls/table-sessions/<uuid:pk>/merge/', TableSessionMergeView.as_view()),
]
