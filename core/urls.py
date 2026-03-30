from django.contrib import admin
from django.urls import include, path

from common.constants import API_PREFIX, API_V1_PREFIX
from core.yasg import schema_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path(f'{API_PREFIX}i18n/', include('django.conf.urls.i18n')),
    path(f'{API_PREFIX}swagger<format>/', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path(f'{API_PREFIX}swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path(f'{API_PREFIX}redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path(f'{API_V1_PREFIX}dashboard/', include('apps.dashboard.urls')),
    path(f'{API_V1_PREFIX}admin/', include('apps.admin.urls')),
    path(API_V1_PREFIX, include('apps.accounts.urls')),
    path(API_V1_PREFIX, include('apps.floor.urls')),
    path(API_V1_PREFIX, include('apps.catalog.urls')),
    path(API_V1_PREFIX, include('apps.orders.urls')),
    path(API_V1_PREFIX, include('apps.kitchen.urls')),
    path(API_V1_PREFIX, include('apps.reports.urls')),
]
