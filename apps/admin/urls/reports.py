from django.urls import path

from apps.admin.views import (
    DashboardSummaryView,
    OpenChecksReportExportView,
    OpenChecksReportView,
    PaymentBreakdownExportView,
    PaymentBreakdownView,
    SalesReportExportView,
    SalesReportView,
    ShiftReportExportView,
    ShiftReportView,
    SummaryReportExportView,
    TopItemsReportExportView,
    TopItemsReportView,
    TopStaffReportExportView,
    TopStaffReportView,
)

urlpatterns = [
    path('reports/summary/', DashboardSummaryView.as_view()),
    path('reports/summary/export/', SummaryReportExportView.as_view()),
    path('reports/sales/', SalesReportView.as_view()),
    path('reports/sales/export/', SalesReportExportView.as_view()),
    path('reports/open-checks/', OpenChecksReportView.as_view()),
    path('reports/open-checks/export/', OpenChecksReportExportView.as_view()),
    path('reports/top-items/', TopItemsReportView.as_view()),
    path('reports/top-items/export/', TopItemsReportExportView.as_view()),
    path('reports/top-staff/', TopStaffReportView.as_view()),
    path('reports/top-staff/export/', TopStaffReportExportView.as_view()),
    path('reports/payment-breakdown/', PaymentBreakdownView.as_view()),
    path('reports/payment-breakdown/export/', PaymentBreakdownExportView.as_view()),
    path('reports/shifts/', ShiftReportView.as_view()),
    path('reports/shifts/export/', ShiftReportExportView.as_view()),
]
