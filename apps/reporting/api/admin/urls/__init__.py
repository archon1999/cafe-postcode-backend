from django.urls import path

from apps.reporting.api.admin.views.reports import (
    DashboardSummaryView,
    OpenChecksReportExportView,
    OpenChecksReportView,
    PaymentBreakdownExportView,
    PaymentBreakdownView,
    ReceiptsReportExportView,
    ReceiptsReportView,
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
    path('summary/', DashboardSummaryView.as_view()),
    path('summary/export/', SummaryReportExportView.as_view()),
    path('sales/', SalesReportView.as_view()),
    path('sales/export/', SalesReportExportView.as_view()),
    path('open-checks/', OpenChecksReportView.as_view()),
    path('open-checks/export/', OpenChecksReportExportView.as_view()),
    path('receipts/', ReceiptsReportView.as_view()),
    path('receipts/export/', ReceiptsReportExportView.as_view()),
    path('top-items/', TopItemsReportView.as_view()),
    path('top-items/export/', TopItemsReportExportView.as_view()),
    path('top-staff/', TopStaffReportView.as_view()),
    path('top-staff/export/', TopStaffReportExportView.as_view()),
    path('payment-breakdown/', PaymentBreakdownView.as_view()),
    path('payment-breakdown/export/', PaymentBreakdownExportView.as_view()),
    path('shifts/', ShiftReportView.as_view()),
    path('shifts/export/', ShiftReportExportView.as_view()),
]
