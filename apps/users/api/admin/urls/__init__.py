from .auth import urlpatterns as auth_urlpatterns
from .employees import urlpatterns as employee_urlpatterns
from .permissions import urlpatterns as permission_urlpatterns
from .roles import urlpatterns as role_urlpatterns
from .users import urlpatterns as user_urlpatterns

urlpatterns = [
    *auth_urlpatterns,
    *user_urlpatterns,
    *role_urlpatterns,
    *permission_urlpatterns,
    *employee_urlpatterns,
]
