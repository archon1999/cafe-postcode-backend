from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.catalog.models import CatalogCategory, CatalogItem
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import PrepStation, Restaurant
from apps.users.models import Permission, Role, User

@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class CatalogImageApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Catalog Image Restaurant')
        permission_codes = [
            'catalog_categories.create',
            'catalog_categories.update',
            'catalog_items.create',
            'catalog_items.update',
        ]
        permissions = []
        for code in permission_codes:
            permission, _ = Permission.objects.get_or_create(
                code=code,
                defaults={'name': code, 'description': code},
            )
            permissions.append(permission)

        cls.role = Role.objects.get_or_create(
            code='catalog-image-admin',
            defaults={'name': 'Catalog image admin', 'description': 'Catalog image admin', 'is_system': False},
        )[0]
        cls.role.permissions.set(permissions)

        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            is_custom=True,
        )
        cls.entitlement.permissions.set(permissions)
        cls.entitlement.allowed_roles.set([cls.role])

        cls.user = User.objects.create_user(
            username='catalog-image-admin',
            password='secret123',
            full_name='Catalog Image Admin',
            restaurant=cls.restaurant,
            role=cls.role,
            is_staff=True,
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.restaurant,
            name='Fast food',
            mxik_code='00709001906000000',
            mxik_name='Fast food',
            mxik_payload={'mxikCode': '00709001906000000', 'mxikName': 'Fast food'},
            sort_order=1,
            is_active=True,
        )
        cls.prep_station = PrepStation.objects.create(
            restaurant=cls.restaurant,
            name='Main kitchen',
            kind=PrepStation.Kind.KITCHEN,
            is_active=True,
        )

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.category_storage = CatalogCategory._meta.get_field('image_file').storage
        self.item_storage = CatalogItem._meta.get_field('image_file').storage

        self.category_save_patcher = patch.object(
            self.category_storage,
            'save',
            side_effect=lambda name, content, max_length=None: f'catalog/categories/{name.replace("\\\\", "/")}',
        )
        self.category_delete_patcher = patch.object(self.category_storage, 'delete')
        self.category_url_patcher = patch.object(
            self.category_storage,
            'url',
            side_effect=lambda name, *args, **kwargs: f'https://cdn.example.com/{name}',
        )
        self.item_save_patcher = patch.object(
            self.item_storage,
            'save',
            side_effect=lambda name, content, max_length=None: f'catalog/items/{name.replace("\\\\", "/")}',
        )
        self.item_delete_patcher = patch.object(self.item_storage, 'delete')
        self.item_url_patcher = patch.object(
            self.item_storage,
            'url',
            side_effect=lambda name, *args, **kwargs: f'https://cdn.example.com/{name}',
        )

        self.category_save_mock = self.category_save_patcher.start()
        self.category_delete_mock = self.category_delete_patcher.start()
        self.category_url_mock = self.category_url_patcher.start()
        self.item_save_mock = self.item_save_patcher.start()
        self.item_delete_mock = self.item_delete_patcher.start()
        self.item_url_mock = self.item_url_patcher.start()

        self.addCleanup(self.category_save_patcher.stop)
        self.addCleanup(self.category_delete_patcher.stop)
        self.addCleanup(self.category_url_patcher.stop)
        self.addCleanup(self.item_save_patcher.stop)
        self.addCleanup(self.item_delete_patcher.stop)
        self.addCleanup(self.item_url_patcher.stop)

    @staticmethod
    def make_image_file(name='image.png'):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buffer = BytesIO()
        Image.new('RGB', (1, 1), color=(255, 0, 0)).save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def test_category_create_accepts_multipart_mxik_payload_and_manual_override(self):
        mxik_image_url = 'https://mxik.example.com/1001.png'
        response = self.client.post(
            '/api/v1/admin/catalog/categories/',
            data={
                'name': 'Salatlar',
                'mxikCode': '00709001906000001',
                'mxikName': 'Salat barg',
                'mxikPayload': '{"mxikCode":"00709001906000001","mxikName":"Salat barg"}',
                'imageUrl': mxik_image_url,
                'imageSource': 'manual',
                'imageFile': self.make_image_file(),
                'sortOrder': '2',
                'isActive': 'true',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        created = CatalogCategory.objects.get(pk=response.data['id'])

        self.assertEqual(created.image_url, mxik_image_url)
        self.assertEqual(created.image_source, CatalogCategory.ImageSource.MANUAL)
        self.assertTrue(created.image_file.name)
        self.assertEqual(response.data['image_source'], CatalogCategory.ImageSource.MANUAL)
        self.assertEqual(response.data['image_url'], f'https://cdn.example.com/{created.image_file.name}')

    def test_category_update_keeps_manual_image_for_mxik_change_and_restore_removes_old_file(self):
        category = CatalogCategory.objects.create(
            restaurant=self.restaurant,
            name='Burger',
            mxik_code='00709001906000000',
            mxik_name='Burger',
            mxik_payload={'mxikCode': '00709001906000000', 'mxikName': 'Burger'},
            image_url='https://mxik.example.com/old.png',
            image_source=CatalogCategory.ImageSource.MANUAL,
            image_file='catalog/categories/existing/manual-old.png',
            sort_order=3,
            is_active=True,
        )

        keep_manual_response = self.client.put(
            f'/api/v1/admin/catalog/categories/{category.id}/',
            data={
                'name': 'Burger',
                'mxikCode': '00709001906000002',
                'mxikName': 'Burger premium',
                'mxikPayload': '{"mxikCode":"00709001906000002","mxikName":"Burger premium"}',
                'imageUrl': 'https://mxik.example.com/new.png',
                'imageSource': 'manual',
                'sortOrder': '3',
                'isActive': 'true',
            },
            format='multipart',
        )

        self.assertEqual(keep_manual_response.status_code, status.HTTP_200_OK, keep_manual_response.data)
        category.refresh_from_db()
        self.assertEqual(category.image_source, CatalogCategory.ImageSource.MANUAL)
        self.assertEqual(category.image_url, 'https://mxik.example.com/new.png')
        self.assertEqual(
            keep_manual_response.data['image_url'],
            f'https://cdn.example.com/{category.image_file.name}',
        )

        restore_response = self.client.put(
            f'/api/v1/admin/catalog/categories/{category.id}/',
            data={
                'name': 'Burger',
                'mxikCode': '00709001906000002',
                'mxikName': 'Burger premium',
                'mxikPayload': '{"mxikCode":"00709001906000002","mxikName":"Burger premium"}',
                'imageUrl': 'https://mxik.example.com/new.png',
                'restoreMxikImage': 'true',
                'sortOrder': '3',
                'isActive': 'true',
            },
            format='multipart',
        )

        self.assertEqual(restore_response.status_code, status.HTTP_200_OK, restore_response.data)
        category.refresh_from_db()
        self.assertEqual(category.image_source, CatalogCategory.ImageSource.MXIK_CACHE)
        self.assertFalse(category.image_file.name)
        self.assertEqual(restore_response.data['image_url'], 'https://mxik.example.com/new.png')
        self.category_delete_mock.assert_called_with('catalog/categories/existing/manual-old.png')

    def test_item_create_uses_cached_mxik_image_when_manual_image_missing(self):
        mxik_image_url = 'https://mxik.example.com/item.png'
        response = self.client.post(
            '/api/v1/admin/catalog/items/',
            data={
                'name': 'Lavash',
                'category': str(self.category.id),
                'prepStation': str(self.prep_station.id),
                'mxikCode': '00709001906000003',
                'mxikName': 'Lavash',
                'mxikPayload': '{"mxikCode":"00709001906000003","mxikName":"Lavash"}',
                'imageUrl': mxik_image_url,
                'imageSource': 'mxik-cache',
                'description': 'Issiq mahsulot',
                'price': '32000',
                'isActive': 'true',
                'isStoplisted': 'false',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        created = CatalogItem.objects.get(pk=response.data['id'])
        self.assertEqual(created.image_url, mxik_image_url)
        self.assertEqual(created.image_source, CatalogItem.ImageSource.MXIK_CACHE)
        self.assertEqual(response.data['image_url'], mxik_image_url)

    def test_item_manual_replace_cleans_old_file_and_restore_uses_cached_mxik(self):
        item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            prep_station=self.prep_station,
            name='Pizza',
            mxik_code='00709001906000004',
            mxik_name='Pizza',
            mxik_payload={'mxikCode': '00709001906000004', 'mxikName': 'Pizza'},
            image_url='https://mxik.example.com/pizza-old.png',
            image_source=CatalogItem.ImageSource.MANUAL,
            image_file='catalog/items/existing/manual-old.png',
            description='Pishloqli',
            price=45000,
            is_active=True,
            is_stoplisted=False,
        )

        replace_response = self.client.put(
            f'/api/v1/admin/catalog/items/{item.id}/',
            data={
                'name': 'Pizza',
                'category': str(self.category.id),
                'prepStation': str(self.prep_station.id),
                'mxikCode': '00709001906000005',
                'mxikName': 'Pizza premium',
                'mxikPayload': '{"mxikCode":"00709001906000005","mxikName":"Pizza premium"}',
                'imageUrl': 'https://mxik.example.com/pizza-new.png',
                'imageFile': self.make_image_file('pizza.png'),
                'description': 'Pishloqli',
                'price': '45000',
                'isActive': 'true',
                'isStoplisted': 'false',
            },
            format='multipart',
        )

        self.assertEqual(replace_response.status_code, status.HTTP_200_OK, replace_response.data)
        item.refresh_from_db()
        self.assertEqual(item.image_source, CatalogItem.ImageSource.MANUAL)
        self.assertEqual(item.image_url, 'https://mxik.example.com/pizza-new.png')
        self.item_delete_mock.assert_called_with('catalog/items/existing/manual-old.png')

        previous_manual_path = item.image_file.name
        restore_response = self.client.put(
            f'/api/v1/admin/catalog/items/{item.id}/',
            data={
                'name': 'Pizza',
                'category': str(self.category.id),
                'prepStation': str(self.prep_station.id),
                'mxikCode': '00709001906000005',
                'mxikName': 'Pizza premium',
                'mxikPayload': '{"mxikCode":"00709001906000005","mxikName":"Pizza premium"}',
                'imageUrl': 'https://mxik.example.com/pizza-new.png',
                'restoreMxikImage': 'true',
                'description': 'Pishloqli',
                'price': '45000',
                'isActive': 'true',
                'isStoplisted': 'false',
            },
            format='multipart',
        )

        self.assertEqual(restore_response.status_code, status.HTTP_200_OK, restore_response.data)
        item.refresh_from_db()
        self.assertEqual(item.image_source, CatalogItem.ImageSource.MXIK_CACHE)
        self.assertFalse(item.image_file.name)
        self.assertEqual(restore_response.data['image_url'], 'https://mxik.example.com/pizza-new.png')
        self.item_delete_mock.assert_called_with(previous_manual_path)
