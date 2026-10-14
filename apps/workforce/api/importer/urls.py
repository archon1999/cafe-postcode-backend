from django.urls import path

from apps.workforce.api.importer.views import HikvisionPunchImportView

urlpatterns = [path('attendance/import/', HikvisionPunchImportView.as_view())]
