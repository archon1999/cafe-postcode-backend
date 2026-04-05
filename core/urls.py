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
    path(f'{API_V1_PREFIX}dashboard/', include('apps.dashboard.api.urls')),
    path(f'{API_V1_PREFIX}admin/auth/', include('apps.users.api.admin.urls.auth')),
    path(f'{API_V1_PREFIX}admin/users/', include('apps.users.api.admin.urls.users')),
    path(f'{API_V1_PREFIX}admin/roles/', include('apps.users.api.admin.urls.roles')),
    path(f'{API_V1_PREFIX}admin/permissions/', include('apps.users.api.admin.urls.permissions')),
    path(f'{API_V1_PREFIX}admin/employees/', include('apps.users.api.admin.urls.employees')),
    path(f'{API_V1_PREFIX}admin/platform/', include('apps.platform.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/restaurants/', include('apps.restaurants.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/catalog/', include('apps.catalog.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/floor/', include('apps.floor.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/sales/', include('apps.sales.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/billing/', include('apps.billing.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/kitchen/', include('apps.kitchen.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/reporting/', include('apps.reporting.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/integrations/', include('apps.integrations.api.admin.urls')),
    path(f'{API_V1_PREFIX}pos/auth/', include('apps.users.api.pos.urls.auth')),
    path(f'{API_V1_PREFIX}pos/catalog/', include('apps.catalog.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/floor/', include('apps.floor.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/sales/', include('apps.sales.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/billing/', include('apps.billing.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/kitchen/', include('apps.kitchen.api.pos.urls')),
]
