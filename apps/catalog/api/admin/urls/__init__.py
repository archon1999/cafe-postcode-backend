from django.urls import path

from apps.catalog.api.admin.views.categories import CategoryDetailView, CategoryListCreateView
from apps.catalog.api.admin.views.items import ItemDetailView, ItemListCreateView, ItemStoplistToggleView
from apps.catalog.api.admin.views.mxik import MxikLookupView, MxikSearchView

urlpatterns = [
    path('categories/', CategoryListCreateView.as_view()),
    path('categories/<uuid:pk>/', CategoryDetailView.as_view()),
    path('items/', ItemListCreateView.as_view()),
    path('items/<uuid:pk>/', ItemDetailView.as_view()),
    path('items/<uuid:pk>/stoplist/', ItemStoplistToggleView.as_view()),
    path('mxik/search/', MxikSearchView.as_view()),
    path('mxik/<str:code>/', MxikLookupView.as_view()),
]
