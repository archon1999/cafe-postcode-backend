from django.urls import path

from .views import (
    PrintPresetCatalogView,
    PrintTemplateDetailView,
    PrintTemplateListView,
    PrintTemplateVersionCreateView,
    PrintTemplateVersionPublishView,
)

urlpatterns = [
    path('presets/', PrintPresetCatalogView.as_view()),
    path('templates/', PrintTemplateListView.as_view()),
    path('templates/<uuid:pk>/', PrintTemplateDetailView.as_view()),
    path('templates/<uuid:pk>/versions/', PrintTemplateVersionCreateView.as_view()),
    path(
        'templates/<uuid:pk>/versions/<uuid:version_pk>/publish/',
        PrintTemplateVersionPublishView.as_view(),
    ),
]
