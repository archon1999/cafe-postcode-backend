from django.test import SimpleTestCase

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers import CatalogCategorySerializer


class CatalogCategorySerializerTests(SimpleTestCase):
    def test_create_uses_frontend_mxik_payload_without_external_lookup(self):
        mxik_payload = {
            'mxikCode': '00709001906000000',
            'mxikName': 'Salat barg',
            'positionName': 'Sabzavotlar',
        }

        serializer = CatalogCategorySerializer(
            data={
                'name': 'Sabzavotlar',
                'mxik_code': '00709001906000000',
                'mxik_name': 'Salat barg',
                'mxik_payload': mxik_payload,
                'image_url': 'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00709001906000000_1.png',
                'image_source': CatalogCategory.ImageSource.MXIK_CACHE,
                'sort_order': 1,
                'is_active': True,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['mxik_name'], 'Salat barg')
        self.assertEqual(serializer.validated_data['mxik_payload'], mxik_payload)
        self.assertEqual(
            serializer.validated_data['image_url'],
            'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00709001906000000_1.png',
        )
        self.assertEqual(serializer.validated_data['image_source'], CatalogCategory.ImageSource.MXIK_CACHE)

    def test_create_derives_mxik_name_from_payload_when_name_is_missing(self):
        serializer = CatalogCategorySerializer(
            data={
                'name': 'Sabzavotlar',
                'mxik_code': '00709001906000000',
                'mxik_payload': {
                    'mxikCode': '00709001906000000',
                    'subPositionName': 'Kartoshka',
                    'positionName': 'Sabzavotlar',
                },
                'sort_order': 1,
                'is_active': True,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['mxik_name'], 'Kartoshka / Sabzavotlar')

    def test_update_clears_payload_and_cached_mxik_image_when_code_removed(self):
        instance = CatalogCategory(
            name='Sabzavotlar',
            mxik_code='00709001906000000',
            mxik_name='Salat barg',
            mxik_payload={'mxikCode': '00709001906000000', 'mxikName': 'Salat barg'},
            image_url='https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00709001906000000_1.png',
            image_source=CatalogCategory.ImageSource.MXIK_CACHE,
            sort_order=1,
            is_active=True,
        )

        serializer = CatalogCategorySerializer(
            instance=instance,
            data={
                'name': 'Sabzavotlar',
                'mxik_code': '',
                'mxik_name': '',
                'mxik_payload': {},
                'sort_order': 1,
                'is_active': True,
            },
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['mxik_payload'], {})
        self.assertIsNone(serializer.validated_data['image_url'])
        self.assertEqual(serializer.validated_data['image_source'], '')
