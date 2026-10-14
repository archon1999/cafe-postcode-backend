from django.urls import path

from apps.workforce.api.staff.views import (
    MyAttendanceListView, MyCorrectionListCreateView, MyPunchSelfieView, MyPunchView,
    MyShiftListView, MyTimesheetListView, TodayView,
)

urlpatterns = [
    path('today/', TodayView.as_view()),
    path('shifts/', MyShiftListView.as_view()),
    path('attendance/', MyAttendanceListView.as_view()),
    path('attendance/punch/', MyPunchView.as_view()),
    path('attendance/<uuid:punch_id>/selfie/', MyPunchSelfieView.as_view()),
    path('timesheets/', MyTimesheetListView.as_view()),
    path('corrections/', MyCorrectionListCreateView.as_view()),
]
