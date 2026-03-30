from django.urls import path

from .views import (
    DashboardSummaryView,
    OpenChecksReportView,
    PaymentBreakdownView,
    SalesReportView,
    SalesReportExportView,
    TopItemsReportView,
    TopStaffReportView,
)

urlpatterns = [
    path('reports/summary/', DashboardSummaryView.as_view()),
    path('reports/sales/', SalesReportView.as_view()),
    path('reports/sales/export/', SalesReportExportView.as_view()),
    path('reports/open-checks/', OpenChecksReportView.as_view()),
    path('reports/top-items/', TopItemsReportView.as_view()),
    path('reports/top-staff/', TopStaffReportView.as_view()),
    path('reports/payment-breakdown/', PaymentBreakdownView.as_view()),
]
