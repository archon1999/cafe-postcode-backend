from django.urls import path
from . import views
from .ai_views import InventoryAnalysisView

urlpatterns = [
    path('warehouses/', views.WarehousesListView.as_view()),
    path('warehouses/<uuid:pk>/', views.WarehousesDetailView.as_view()),
    path('items/', views.ItemsListView.as_view()),
    path('items/<uuid:pk>/', views.ItemsDetailView.as_view()),
    path('suppliers/', views.SuppliersListView.as_view()),
    path('suppliers/<uuid:pk>/', views.SuppliersDetailView.as_view()),
    path('catalog-options/', views.CatalogOptionsView.as_view()),
    path('recipes/', views.RecipesListView.as_view()),
    path('recipes/<uuid:pk>/', views.RecipesDetailView.as_view()),
    path('documents/', views.DocumentsListView.as_view()),
    path('documents/<uuid:pk>/', views.DocumentsDetailView.as_view()),
    path('documents/<uuid:pk>/post/', views.PostDocumentView.as_view()),
    path('documents/<uuid:pk>/reverse/', views.ReverseDocumentView.as_view()),
    path('documents/<uuid:pk>/export/', views.DocumentExportView.as_view()),
    path('balances/', views.ReportView.as_view(report='balances')),
    path('movements/', views.ReportView.as_view(report='movements')),
    path('overview/', views.ReportView.as_view(report='overview')),
    path('variance/', views.ReportView.as_view(report='variance')),
    path('insights/', views.ReportView.as_view(report='insights')),
    path('insights/analyze/', InventoryAnalysisView.as_view()),
    path('export/', views.ExportView.as_view()),
    path('attachments/', views.AttachmentsView.as_view()),
    path('attachments/<uuid:pk>/download/', views.AttachmentDownloadView.as_view()),
]
