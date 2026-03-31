from .auth_users import urlpatterns as auth_user_urlpatterns
from .business_partner import urlpatterns as business_partner_urlpatterns
from .catalog import urlpatterns as catalog_urlpatterns
from .constructor import urlpatterns as constructor_urlpatterns
from .operations import urlpatterns as operations_urlpatterns
from .product_owner import urlpatterns as product_owner_urlpatterns
from .reports import urlpatterns as report_urlpatterns

urlpatterns = [
    *auth_user_urlpatterns,
    *business_partner_urlpatterns,
    *catalog_urlpatterns,
    *constructor_urlpatterns,
    *operations_urlpatterns,
    *product_owner_urlpatterns,
    *report_urlpatterns,
]

__all__ = [
    'urlpatterns',
]
