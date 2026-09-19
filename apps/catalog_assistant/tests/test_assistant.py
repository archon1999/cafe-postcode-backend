import io
from datetime import timedelta
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook
from PIL import Image
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.test import APITestCase
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.platform.models import BusinessPartner, RestaurantEntitlement
from apps.restaurants.models import Restaurant
from apps.users.models import User, Role, Permission
from apps.catalog_assistant.access import restaurants_for, require_access
from apps.catalog_assistant.drafts import commit_draft, create_draft
from apps.catalog_assistant.inputs import normalize_input
from apps.catalog_assistant.links import consume_link, issue_link
from apps.catalog_assistant.models import CatalogDraft, ManagementBotAccount


def sample_row(category):
    return {'selected': True, 'name': 'Osh', 'name_ru': 'Плов', 'category_id': str(category.pk),
            'category_name': category.name, 'category_mxik': '', 'price': 35000, 'sale_unit': 'piece',
            'description': '', 'evidence': 'Osh 35 ming', 'warning': ''}


@override_settings(ALLOWED_HOSTS=['testserver'], MANAGEMENT_BOT_USERNAME='test_postcode_bot')
class DraftTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='One')
        self.other = Restaurant.objects.create(name='Other')
        self.user = User.objects.create_superuser('assistant-root', full_name='Root')
        self.category = CatalogCategory.objects.create(restaurant=self.restaurant, name='Taomlar', mxik_code='00709001906000000')
        self.row = sample_row(self.category)

    def draft(self, rows=None):
        return CatalogDraft.objects.create(owner=self.user, restaurant=self.restaurant,
            rows=rows or [self.row], expires_at=timezone.now() + timedelta(hours=1))

    def test_review_does_not_write_until_commit_and_replay_is_idempotent(self):
        with patch('apps.catalog_assistant.drafts.extract_menu', return_value=[dict(self.row)]):
            draft = create_draft(self.user, self.restaurant.pk, [], self.category.pk)
        self.assertFalse(CatalogItem.objects.exists())
        with patch('apps.catalog_assistant.drafts.broadcast_configuration_invalidation') as notify, self.captureOnCommitCallbacks(execute=True):
            result = commit_draft(self.user, draft.pk, draft.rows, 1)
        self.assertEqual(result.result['count'], 1)
        notify.assert_called_once_with(restaurant_id=self.restaurant.pk)
        commit_draft(self.user, draft.pk, draft.rows, 1)
        self.assertEqual(CatalogItem.objects.count(), 1)

    def test_unknown_price_is_not_zero_and_all_rows_rollback(self):
        rows = [self.row, {**self.row, 'name': 'Choy', 'price': None}]
        draft = self.draft(rows)
        with self.assertRaises(ValidationError):
            commit_draft(self.user, draft.pk, rows, 1)
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_foreign_category_rejected(self):
        foreign = CatalogCategory.objects.create(restaurant=self.other, name='Foreign')
        row = {**self.row, 'category_id': str(foreign.pk)}
        with self.assertRaises(Http404):
            commit_draft(self.user, self.draft().pk, [row], 1)
        self.assertFalse(CatalogItem.objects.exists())

    def test_owner_and_revision_are_enforced(self):
        draft = self.draft()
        stranger = User.objects.create_superuser('stranger', full_name='Stranger')
        with self.assertRaises(Http404):
            commit_draft(stranger, draft.pk, [self.row], 1)
        with self.assertRaises(ValidationError):
            commit_draft(self.user, draft.pk, [self.row], 99)

    def test_new_category_requires_mxik(self):
        row = {**self.row, 'category_id': None, 'category_name': 'Ichimliklar'}
        draft = self.draft()
        with self.assertRaises(ValidationError):
            commit_draft(self.user, draft.pk, [row], 1)
        row['category_mxik'] = '00709001906000000'
        commit_draft(self.user, draft.pk, [row], 1)
        self.assertEqual(CatalogItem.objects.get().category.name, 'Ichimliklar')

    def test_deselected_rows_are_not_written(self):
        rows = [self.row, {**self.row, 'selected': False, 'price': None}]
        commit_draft(self.user, self.draft().pk, rows, 1)
        self.assertEqual(CatalogItem.objects.count(), 1)

    def test_expired_draft_rejected(self):
        draft = self.draft()
        draft.expires_at = timezone.now() - timedelta(seconds=1)
        draft.save()
        with self.assertRaises(ValidationError):
            commit_draft(self.user, draft.pk, [self.row], 1)

    def test_api_camel_case_round_trip(self):
        self.client.force_authenticate(self.user)
        with patch('apps.catalog_assistant.drafts.extract_menu', return_value=[dict(self.row)]):
            response = self.client.post('/api/v1/admin/catalog-assistant/drafts/', {
                'text': 'Osh 35000', 'restaurantId': str(self.restaurant.pk), 'categoryId': str(self.category.pk),
            }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        payload = response.json()
        self.assertIn('categoryId', payload['rows'][0])
        result = self.client.post(f'/api/v1/admin/catalog-assistant/drafts/{payload["id"]}/commit/', {
            'rows': payload['rows'], 'revision': payload['revision'],
        }, format='json')
        self.assertEqual(result.status_code, 200, result.data)

    def test_one_use_link_rotation_and_disabled_user(self):
        first = issue_link(self.user)['url'].split('start=')[1]
        second = issue_link(self.user)['url'].split('start=')[1]
        with self.assertRaises(ValidationError):
            consume_link(first, 123, 123)
        consume_link(second, 123, 123)
        with self.assertRaises(ValidationError):
            consume_link(second, 456, 456)
        self.user.is_active = False
        self.user.save()
        self.assertFalse(restaurants_for(self.user).exists())

    def test_link_cannot_take_over_another_telegram_account(self):
        other_user = User.objects.create_superuser('other-root', full_name='Other')
        ManagementBotAccount.objects.create(user=other_user, telegram_user_id=123, chat_id=123)
        token = issue_link(self.user)['url'].split('start=')[1]
        with self.assertRaises(ValidationError):
            consume_link(token, 123, 123)

    def test_partner_only_sees_assigned_active_restaurants(self):
        partner_user = User.objects.create_user('partner', full_name='Partner')
        partner = BusinessPartner.objects.create(owner_user=partner_user, inn='123', company_name='Partner', status='active')
        self.restaurant.business_partner = partner
        self.restaurant.save()
        self.assertEqual(list(restaurants_for(partner_user)), [self.restaurant])
        with self.assertRaises(Http404):
            require_access(partner_user, self.other.pk)
        partner.status = 'inactive'
        partner.save()
        partner_user.refresh_from_db()
        self.assertFalse(restaurants_for(partner_user).exists())

    def test_restaurant_admin_needs_current_permission(self):
        role, _ = Role.objects.get_or_create(code='restaurant_admin', defaults={'name': 'Admin'})
        role.permissions.clear()
        permission, _ = Permission.objects.get_or_create(code='catalog_items.create', defaults={'name': 'Create'})
        role.permissions.add(permission)
        entitlement = RestaurantEntitlement.objects.create(restaurant=self.restaurant, is_active=True, is_custom=True)
        entitlement.permissions.add(permission)
        admin = User.objects.create_user('admin', full_name='Admin', role=role, restaurant=self.restaurant)
        self.assertEqual(require_access(admin, self.restaurant.pk), self.restaurant)
        with self.assertRaises(Http404):
            require_access(admin, self.other.pk)
        role.permissions.clear()
        with self.assertRaises(PermissionDenied):
            require_access(admin, self.restaurant.pk)


class InputTests(TestCase):
    def test_xlsx_keeps_zero_and_does_not_execute_formula(self):
        book = Workbook()
        book.active.append(['Choy', 0])
        book.active.append(['Other', '=1+2'])
        output = io.BytesIO()
        book.save(output)
        content = normalize_input(files=[SimpleUploadedFile('menu.xlsx', output.getvalue())])
        self.assertIn('Choy\t0', content[0]['text'])
        self.assertNotIn('=1+2', content[0]['text'])

    def test_image_is_decoded_and_reencoded(self):
        output = io.BytesIO()
        Image.new('RGB', (32, 32)).save(output, format='PNG')
        content = normalize_input(files=[SimpleUploadedFile('menu.png', output.getvalue())])
        self.assertTrue(content[0]['image_url'].startswith('data:image/jpeg;base64,'))

    def test_reject_empty_and_non_image(self):
        with self.assertRaises(ValidationError):
            normalize_input()
        with self.assertRaises(ValidationError):
            normalize_input(files=[SimpleUploadedFile('menu.png', b'not an image')])
