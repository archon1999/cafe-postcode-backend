from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.restaurants.api.admin.serializers import RestaurantSerializer
from apps.restaurants.models import Restaurant


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class RestaurantAuthBackgroundSerializerTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            name='Auth Background Restaurant',
            legal_name='Auth Background LLC',
            tax_number='123456789',
            phone='+998900000000',
            address='Tashkent',
        )
        self.storage = Restaurant._meta.get_field('pos_auth_background_image').storage
        self.save_patcher = patch.object(
            self.storage,
            'save',
            side_effect=lambda name, content, max_length=None: f'restaurants/auth-backgrounds/{name.replace("\\\\", "/")}',
        )
        self.delete_patcher = patch.object(self.storage, 'delete')
        self.url_patcher = patch.object(
            self.storage,
            'url',
            side_effect=lambda name, *args, **kwargs: f'https://cdn.example.com/{name}',
        )

        self.save_patcher.start()
        self.delete_mock = self.delete_patcher.start()
        self.url_patcher.start()

        self.addCleanup(self.save_patcher.stop)
        self.addCleanup(self.delete_patcher.stop)
        self.addCleanup(self.url_patcher.stop)

    @staticmethod
    def make_image_file(name='login.png'):
        buffer = BytesIO()
        Image.new('RGB', (1, 1), color=(255, 0, 0)).save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def base_payload(self):
        return {
            'name': self.restaurant.name,
            'legal_name': self.restaurant.legal_name,
            'tax_number': self.restaurant.tax_number,
            'phone': self.restaurant.phone,
            'address': self.restaurant.address,
            'service_fee_enabled': True,
            'service_fee_percent': '10',
            'vat_enabled': False,
            'vat_percent': '12',
            'is_active': True,
        }

    def test_representation_returns_empty_background_url_without_image(self):
        data = RestaurantSerializer(self.restaurant).data

        self.assertIsNone(data['pos_auth_background_image_url'])
        self.assertFalse(data['service_fee_enabled'])
        self.assertEqual(data['service_fee_percent'], '0.00')
        self.assertTrue(data['vat_enabled'])
        self.assertEqual(data['vat_percent'], '12.00')
        self.assertEqual(data['pos_monitor_variant'], Restaurant.PosMonitorVariant.DEFAULT)

    def test_update_persists_pos_monitor_variant(self):
        serializer = RestaurantSerializer(
            self.restaurant,
            data={**self.base_payload(), 'pos_monitor_variant': Restaurant.PosMonitorVariant.LIGHT_COMPACT},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        restaurant = serializer.save()

        self.assertEqual(restaurant.pos_monitor_variant, Restaurant.PosMonitorVariant.LIGHT_COMPACT)
        self.assertEqual(
            RestaurantSerializer(restaurant).data['pos_monitor_variant'],
            Restaurant.PosMonitorVariant.LIGHT_COMPACT,
        )

    def test_update_persists_service_fee_percent(self):
        serializer = RestaurantSerializer(self.restaurant, data={**self.base_payload(), 'service_fee_percent': '7.5'})

        self.assertTrue(serializer.is_valid(), serializer.errors)
        restaurant = serializer.save()

        self.assertEqual(str(restaurant.service_fee_percent), '7.50')
        self.assertEqual(RestaurantSerializer(restaurant).data['service_fee_percent'], '7.50')

    def test_update_uploads_and_replaces_background_image(self):
        serializer = RestaurantSerializer(
            self.restaurant,
            data={**self.base_payload(), 'pos_auth_background_image': self.make_image_file()},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        restaurant = serializer.save()

        self.assertTrue(restaurant.pos_auth_background_image.name)
        self.assertEqual(
            RestaurantSerializer(restaurant).data['pos_auth_background_image_url'],
            f'https://cdn.example.com/{restaurant.pos_auth_background_image.name}',
        )

        old_image_name = restaurant.pos_auth_background_image.name
        replace_serializer = RestaurantSerializer(
            restaurant,
            data={**self.base_payload(), 'pos_auth_background_image': self.make_image_file('replacement.png')},
        )

        self.assertTrue(replace_serializer.is_valid(), replace_serializer.errors)
        replaced_restaurant = replace_serializer.save()

        self.assertNotEqual(replaced_restaurant.pos_auth_background_image.name, old_image_name)
        self.delete_mock.assert_called_with(old_image_name)

    def test_clear_background_image_removes_existing_file(self):
        self.restaurant.pos_auth_background_image = 'restaurants/auth-backgrounds/existing/login.png'
        self.restaurant.save(update_fields=['pos_auth_background_image'])

        serializer = RestaurantSerializer(
            self.restaurant,
            data={**self.base_payload(), 'clear_pos_auth_background_image': True},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        restaurant = serializer.save()

        self.assertFalse(restaurant.pos_auth_background_image.name)
        self.assertIsNone(RestaurantSerializer(restaurant).data['pos_auth_background_image_url'])
        self.delete_mock.assert_called_with('restaurants/auth-backgrounds/existing/login.png')
