from .auth_users import urlpatterns as auth_user_urlpatterns
from .catalog import urlpatterns as catalog_urlpatterns
from .constructor import urlpatterns as constructor_urlpatterns
from .operations import urlpatterns as operations_urlpatterns
from .platform import urlpatterns as platform_urlpatterns
from .reports import urlpatterns as report_urlpatterns

urlpatterns = [
    *auth_user_urlpatterns,
    *catalog_urlpatterns,
    *constructor_urlpatterns,
    *operations_urlpatterns,
    *platform_urlpatterns,
    *report_urlpatterns,
]

__all__ = [
    'urlpatterns',
]
