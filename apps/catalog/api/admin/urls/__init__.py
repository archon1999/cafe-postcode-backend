from django.urls import path

from apps.catalog.api.admin.views.categories import CategoryDetailView, CategoryListCreateView
from apps.catalog.api.admin.views.items import ItemDetailView, ItemListCreateView, ItemStoplistToggleView
from apps.catalog.api.admin.views.translations import CatalogNameTranslationView
from apps.catalog.views.modifiers import ModifierGroupDetailView, ModifierGroupListCreateView
from apps.catalog.views.item_groups import ItemGroupDetailView, ItemGroupListCreateView

urlpatterns = [
    path('categories/', CategoryListCreateView.as_view()),
    path('categories/<uuid:pk>/', CategoryDetailView.as_view()),
    path('items/', ItemListCreateView.as_view()),
    path('items/<uuid:pk>/', ItemDetailView.as_view()),
    path('items/<uuid:pk>/stoplist/', ItemStoplistToggleView.as_view()),
    path('item-groups/', ItemGroupListCreateView.as_view()),
    path('item-groups/<uuid:pk>/', ItemGroupDetailView.as_view()),
    path('modifier-groups/', ModifierGroupListCreateView.as_view()),
    path('modifier-groups/<uuid:pk>/', ModifierGroupDetailView.as_view()),
    path('translations/name/', CatalogNameTranslationView.as_view()),
]
