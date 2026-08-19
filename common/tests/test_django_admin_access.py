from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.admin_access import DjangoAdminNetworkMiddleware, django_admin_urlpatterns


class DjangoAdminAccessTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = DjangoAdminNetworkMiddleware(lambda _request: HttpResponse('allowed'))

    @override_settings(DJANGO_ADMIN_ENABLED=False)
    def test_admin_route_and_middleware_are_disabled(self):
        self.assertEqual(django_admin_urlpatterns(), [])
        response = self.middleware(self.factory.get('/admin/', REMOTE_ADDR='10.10.10.10'))
        self.assertEqual(response.status_code, 404)

    @override_settings(
        DJANGO_ADMIN_ENABLED=True,
        DJANGO_PRODUCTION=True,
        DJANGO_ADMIN_ALLOWED_CIDRS=['10.0.0.0/8'],
        DJANGO_ADMIN_TRUSTED_PROXY_CIDRS=['127.0.0.1/32'],
    )
    def test_production_admin_requires_allowlisted_client(self):
        allowed = self.middleware(self.factory.get('/admin/', REMOTE_ADDR='10.20.30.40'))
        denied = self.middleware(self.factory.get('/admin/', REMOTE_ADDR='8.8.8.8'))
        spoofed = self.middleware(
            self.factory.get(
                '/admin/',
                REMOTE_ADDR='8.8.8.8',
                HTTP_X_FORWARDED_FOR='10.20.30.40',
            )
        )
        proxied = self.middleware(
            self.factory.get(
                '/admin/',
                REMOTE_ADDR='127.0.0.1',
                HTTP_X_FORWARDED_FOR='10.20.30.40',
            )
        )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(spoofed.status_code, 404)
        self.assertEqual(proxied.status_code, 200)

    @override_settings(
        DJANGO_ADMIN_ENABLED=True,
        DJANGO_PRODUCTION=True,
        DJANGO_ADMIN_ALLOWED_CIDRS=[],
        DJANGO_ADMIN_TRUSTED_PROXY_CIDRS=[],
    )
    def test_production_misconfiguration_fails_closed(self):
        response = self.middleware(self.factory.get('/admin/', REMOTE_ADDR='127.0.0.1'))
        self.assertEqual(response.status_code, 404)

    @override_settings(
        DJANGO_ADMIN_ENABLED=True,
        DJANGO_PRODUCTION=True,
        DJANGO_ADMIN_ALLOWED_CIDRS=['not-a-cidr'],
        DJANGO_ADMIN_TRUSTED_PROXY_CIDRS=[],
    )
    def test_invalid_allowlist_fails_closed(self):
        response = self.middleware(self.factory.get('/admin/', REMOTE_ADDR='127.0.0.1'))
        self.assertEqual(response.status_code, 404)
