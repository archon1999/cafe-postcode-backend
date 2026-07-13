from django.conf import settings
from django.test import SimpleTestCase

from common.utils.settings import coerce_bool, coerce_int, get_setting


class ConfigSettingsUtilsTests(SimpleTestCase):
    def test_cross_origin_frontends_allow_credentials(self):
        self.assertTrue(settings.CORS_ALLOW_CREDENTIALS)
        self.assertIn('https://admin.cafe-postcode.uz', settings.CORS_ALLOWED_ORIGINS)

    def test_get_setting_uses_first_non_empty_alias(self):
        settings = {'endpoint_url': '', 'endpointUrl': 'http://127.0.0.1:8090'}

        self.assertEqual(get_setting(settings, 'endpoint_url', 'endpointUrl'), 'http://127.0.0.1:8090')
        self.assertEqual(get_setting(settings, 'missing', default='fallback'), 'fallback')

    def test_coerce_bool_accepts_only_known_boolean_forms(self):
        self.assertTrue(coerce_bool('YES'))
        self.assertFalse(coerce_bool('off', default=True))
        self.assertTrue(coerce_bool('unexpected', default=True))
        self.assertFalse(coerce_bool('unexpected'))

    def test_coerce_int_falls_back_and_clamps(self):
        self.assertEqual(coerce_int('9100'), 9100)
        self.assertEqual(coerce_int('bad', default=46), 46)
        self.assertEqual(coerce_int(200, maximum=100), 100)
        self.assertEqual(coerce_int(-1, minimum=0), 0)
