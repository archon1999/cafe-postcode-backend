from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.catalog.serializers import CatalogCategorySerializer
from apps.catalog.models import CatalogCategory


class CatalogCategorySerializerTests(SimpleTestCase):
    @patch('apps.catalog.serializers.mxik.MxikClient')
    def test_create_syncs_mxik_name_and_first_picture_url(self, mxik_client_cls):
        client = mxik_client_cls.return_value
        client.lookup.return_value = {'name': 'Salat barg'}
        client.get_primary_picture_url.return_value = (
            'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00709001906000000_1.png'
        )

        serializer = CatalogCategorySerializer(
            data={
                'name': 'Sabzavotlar',
                'mxik_code': '00709001906000000',
                'sort_order': 1,
                'is_active': True,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['mxik_name'], 'Salat barg')
        self.assertEqual(
            serializer.validated_data['image_url'],
            'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00709001906000000_1.png',
        )
        self.assertEqual(serializer.validated_data['image_source'], CatalogCategory.ImageSource.MXIK_CACHE)

    @patch('apps.catalog.serializers.mxik.MxikClient')
    def test_update_clears_cached_mxik_image_when_code_removed(self, mxik_client_cls):
        instance = CatalogCategory(
            name='Sabzavotlar',
            mxik_code='00709001906000000',
            mxik_name='Salat barg',
            image_url='https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00709001906000000_1.png',
            image_source=CatalogCategory.ImageSource.MXIK_CACHE,
            sort_order=1,
            is_active=True,
        )
        client = mxik_client_cls.return_value
        client.lookup = Mock()
        client.get_primary_picture_url = Mock()

        serializer = CatalogCategorySerializer(
            instance=instance,
            data={
                'name': 'Sabzavotlar',
                'mxik_code': '',
                'mxik_name': '',
                'sort_order': 1,
                'is_active': True,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data['image_url'])
        self.assertEqual(serializer.validated_data['image_source'], '')
        client.lookup.assert_not_called()
        client.get_primary_picture_url.assert_not_called()
