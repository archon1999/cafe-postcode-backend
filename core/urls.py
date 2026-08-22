from django.conf import settings
from django.urls import include, path

from apps.local_agents.pos_views import LocalAgentPOSSystemStatusView
from common.constants import API_PREFIX, API_V1_PREFIX
from core.admin_access import django_admin_urlpatterns
from core.health import healthz, readyz

urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('readyz/', readyz, name='readyz'),
    path(f'{API_V1_PREFIX}system/status/', LocalAgentPOSSystemStatusView.as_view()),
    path('', include('django_prometheus.urls')),
    path(f'{API_PREFIX}i18n/', include('django.conf.urls.i18n')),
    path(f'{API_V1_PREFIX}landing/', include('apps.landing.api.urls')),
    path(f'{API_V1_PREFIX}dashboard/', include('apps.dashboard.api.urls')),
    path(f'{API_V1_PREFIX}telegram-reports/', include('apps.telegram_reports.api.urls')),
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
    path(f'{API_V1_PREFIX}admin/printing/', include('apps.printing.api.admin.urls')),
    path(f'{API_V1_PREFIX}admin/local-agents/', include('apps.local_agents.admin_urls')),
    path(f'{API_V1_PREFIX}admin/telegram-reports/', include('apps.telegram_reports.api.admin_urls')),
    path(f'{API_V1_PREFIX}admin/devices/', include('apps.devices.admin_urls')),
    path(f'{API_V1_PREFIX}admin/monitoring/', include('apps.devices.monitoring_urls')),
    path(f'{API_V1_PREFIX}admin/control/', include('apps.devices.control_urls')),
    path(
        f'{API_V1_PREFIX}admin/security-events/',
        include('apps.devices.security_urls'),
    ),
    path(f'{API_V1_PREFIX}devices/', include('apps.devices.urls')),
    path(f'{API_V1_PREFIX}local-agent/', include('apps.local_agents.urls')),
    path(f'{API_V1_PREFIX}pos/auth/', include('apps.users.api.pos.urls.auth')),
    path(f'{API_V1_PREFIX}pos/catalog/', include('apps.catalog.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/floor/', include('apps.floor.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/sales/', include('apps.sales.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/billing/', include('apps.billing.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/kitchen/', include('apps.kitchen.api.pos.urls')),
    path(f'{API_V1_PREFIX}pos/monitor/', include('apps.kitchen.api.pos.monitor_urls')),
    path(f'{API_V1_PREFIX}pos/printing/', include('apps.printing.api.pos.urls')),
]

urlpatterns = django_admin_urlpatterns() + urlpatterns

if settings.ENABLE_API_DOCS:
    from core.yasg import schema_view

    urlpatterns = [
        path(f'{API_PREFIX}swagger<format>/', schema_view.without_ui(cache_timeout=0), name='schema-json'),
        path(f'{API_PREFIX}swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
        path(f'{API_PREFIX}redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    ] + urlpatterns
