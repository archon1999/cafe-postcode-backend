from unittest.mock import patch

from django.test import SimpleTestCase

from apps.catalog.services.mxik import MxikClient


class MxikClientTests(SimpleTestCase):
    @patch.object(MxikClient, '_request')
    def test_get_primary_picture_url_uses_first_picture_name(self, request_mock):
        request_mock.return_value = ['00709001906000000_1.png', '00709001906000000_2.png']

        image_url = MxikClient().get_primary_picture_url('00709001906000000')

        self.assertEqual(
            image_url,
            'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00709001906000000_1.png',
        )
        request_mock.assert_called_once_with(
            'integration-mxik/references/get/mxik/picture-names',
            {'mxik_code': '00709001906000000', 'lang': 'uz_cyrl'},
        )

    @patch.object(MxikClient, '_request')
    def test_get_primary_picture_url_returns_empty_string_when_no_pictures_exist(self, request_mock):
        request_mock.return_value = {'value': []}

        image_url = MxikClient().get_primary_picture_url('00709001906000000')

        self.assertEqual(image_url, '')
