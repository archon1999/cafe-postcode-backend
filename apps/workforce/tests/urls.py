from django.urls import include, path

urlpatterns = [
    path('api/v1/staff/workforce/', include('apps.workforce.api.staff.urls')),
    path('api/v1/staff/manager/workforce/', include('apps.workforce.api.manage.urls')),
    path('api/v1/local-agent/workforce/', include('apps.workforce.api.importer.urls')),
]
