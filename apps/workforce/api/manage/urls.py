from django.urls import path

from apps.workforce.api.manage.views import (
    AttendanceListView, CorrectionListView, CorrectionResolveView, GeofenceView,
    PunchSelfieView, ShiftDetailView, ShiftListCreateView, ShiftPublishView,
    TeamView, TemplateDetailView, TemplateGenerateView, TemplateListCreateView,
    TimesheetApproveView, TimesheetDetailView, TimesheetListView,
)

urlpatterns = [
    path('team/', TeamView.as_view()),
    path('geofence/', GeofenceView.as_view()),
    path('templates/', TemplateListCreateView.as_view()),
    path('templates/generate/', TemplateGenerateView.as_view()),
    path('templates/<uuid:template_id>/', TemplateDetailView.as_view()),
    path('shifts/', ShiftListCreateView.as_view()),
    path('shifts/publish/', ShiftPublishView.as_view()),
    path('shifts/<uuid:shift_id>/', ShiftDetailView.as_view()),
    path('attendance/', AttendanceListView.as_view()),
    path('attendance/<uuid:punch_id>/selfie/', PunchSelfieView.as_view()),
    path('timesheets/', TimesheetListView.as_view()),
    path('timesheets/<uuid:timesheet_id>/', TimesheetDetailView.as_view()),
    path('timesheets/<uuid:timesheet_id>/approve/', TimesheetApproveView.as_view()),
    path('corrections/', CorrectionListView.as_view()),
    path('corrections/<uuid:correction_id>/resolve/', CorrectionResolveView.as_view()),
]
