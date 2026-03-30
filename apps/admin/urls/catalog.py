from django.urls import path

from apps.admin.views import (
    CategoryDetailView,
    CategoryListCreateView,
    ItemDetailView,
    ItemListCreateView,
    ItemStoplistToggleView,
    MxikLookupView,
    MxikSearchView,
)

urlpatterns = [
    path('catalog/categories/', CategoryListCreateView.as_view()),
    path('catalog/categories/<uuid:pk>/', CategoryDetailView.as_view()),
    path('catalog/items/', ItemListCreateView.as_view()),
    path('catalog/items/<uuid:pk>/', ItemDetailView.as_view()),
    path('catalog/items/<uuid:pk>/stoplist/', ItemStoplistToggleView.as_view()),
    path('catalog/mxik/search/', MxikSearchView.as_view()),
    path('catalog/mxik/<str:code>/', MxikLookupView.as_view()),
]
