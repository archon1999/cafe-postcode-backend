from unittest.mock import patch
from django.test import override_settings
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import ZoneOrCabin, Hall, DiningTable, TableSession, TableSessionTable
from apps.restaurants.models import Restaurant, PrepStation
from apps.telegram_reports.client import TelegramAPIError
from apps.users.models import User
from apps.catalog_assistant.bot import ManagementBotHandler
from apps.catalog_assistant.bot_actions import apply_action
from apps.catalog_assistant.bot_tasks import process_update
from apps.catalog_assistant.models import ManagementBotAccount, ManagementBotUpdate


@override_settings(ALLOWED_HOSTS=['testserver'], MANAGEMENT_BOT_TOKEN='test-token', MANAGEMENT_BOT_WEBHOOK_SECRET='test-secret')
class BotTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('bot-root', full_name='Root')
        self.restaurant = Restaurant.objects.create(name='One')
        self.other = Restaurant.objects.create(name='Other')
        self.account = ManagementBotAccount.objects.create(user=self.user, telegram_user_id=123, chat_id=123, restaurant=self.restaurant)
        self.category = CatalogCategory.objects.create(restaurant=self.restaurant, name='Taomlar')
        self.item = CatalogItem.objects.create(restaurant=self.restaurant, category=self.category, name='Osh', price=100)

    def callback(self, value):
        return {'callback_query': {'id': 'cb', 'from': {'id': 123}, 'data': value,
                                  'message': {'chat': {'id': 123, 'type': 'private'}}}}

    def test_webhook_secret_raw_payload_and_durable_dedup(self):
        url = '/api/v1/management-bot/webhook/'
        payload = {'update_id': 991, 'callback_query': {'id': 'cb'}}
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 403)
        with patch('apps.catalog_assistant.bot_webhook.async_task') as queue:
            response = self.client.post(url, payload, format='json', HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-secret')
        self.assertEqual(response.status_code, 200, response.data)
        queue.assert_called_once()
        update = ManagementBotUpdate.objects.get()
        self.assertIn('callback_query', update.payload)
        update.status = 'done'
        update.save()
        with patch('apps.catalog_assistant.bot_webhook.async_task') as queue:
            self.client.post(url, payload, format='json', HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-secret')
            queue.assert_not_called()
        self.assertEqual(ManagementBotUpdate.objects.count(), 1)

    def test_cross_restaurant_item_and_hall_rejected(self):
        foreign = CatalogItem.objects.create(restaurant=self.other, name='Foreign')
        with self.assertRaises(Http404):
            apply_action(self.account, {'kind': 'item', 'pk': str(foreign.pk), 'data': {'price': 1}})
        zone = ZoneOrCabin.objects.create(restaurant=self.other, name='Foreign')
        with self.assertRaises(Http404):
            apply_action(self.account, {'kind': 'hall', 'data': {'name': 'Hall', 'zone_or_cabin_id': str(zone.pk)}})

    def test_hall_and_table_can_be_created_and_occupied_hall_cannot_hide(self):
        zone = apply_action(self.account, {'kind': 'zone', 'data': {'name': 'Hudud'}})
        hall = apply_action(self.account, {'kind': 'hall', 'data': {'name': 'Zal', 'zone_or_cabin_id': str(zone.pk)}})
        table = apply_action(self.account, {'kind': 'table', 'data': {'name': 'Stol 1', 'hall': str(hall.pk), 'seat_count': 4}})
        TableSession.objects.create(restaurant=self.restaurant, hall=hall, table=table)
        with self.assertRaises(ValidationError):
            apply_action(self.account, {'kind': 'hall', 'pk': str(hall.pk), 'data': {'is_active': False}})
        self.assertEqual(table.seat_count, 4)

    def test_confirm_is_one_use_and_old_button_does_not_repeat(self):
        self.account.state = {'pending': {'kind': 'item', 'pk': str(self.item.pk), 'data': {'price': 200}}, 'nonce': 'abc'}
        self.account.save()
        with patch('apps.catalog_assistant.bot.ManagementBotClient'):
            handler = ManagementBotHandler()
            handler.handle(self.callback('confirm:abc'))
            self.item.refresh_from_db()
            self.assertEqual(self.item.price, 200)
            self.item.price = 300
            self.item.save()
            handler.handle(self.callback('confirm:abc'))
            self.item.refresh_from_db()
            self.assertEqual(self.item.price, 300)

    def test_inline_only_returns_public_mxik_to_linked_users(self):
        with patch('apps.catalog_assistant.bot.ManagementBotClient') as client, patch('apps.catalog_assistant.bot.search_mxik') as search:
            handler = ManagementBotHandler()
            handler.inline({'id': 'inline', 'from': {'id': 999}, 'query': 'osh'})
            search.assert_not_called()
            self.assertEqual(client.return_value.call.call_args.args[1]['results'], [])

    def test_worker_replay_is_noop(self):
        update = ManagementBotUpdate.objects.create(update_id=22, payload={'message': {'text': '/menu', 'from': {'id': 123}, 'chat': {'type': 'private', 'id': 123}}})
        with patch('apps.catalog_assistant.bot.ManagementBotClient') as client:
            process_update(update.pk)
            count = client.return_value.send_message.call_count
            process_update(update.pk)
            self.assertEqual(client.return_value.send_message.call_count, count)
        update.refresh_from_db()
        self.assertEqual(update.payload, {})

    def test_table_capacity_update_and_attached_table_guard(self):
        zone = ZoneOrCabin.objects.create(restaurant=self.restaurant, name='Zone')
        hall = Hall.objects.create(zone_or_cabin=zone, name='Hall')
        table = apply_action(self.account, {'kind': 'table', 'data': {'name': 'Stol 1', 'hall': str(hall.pk), 'seat_count': 4}})
        table = apply_action(self.account, {'kind': 'table', 'pk': str(table.pk), 'data': {'seat_count': 10}})
        self.assertIn(table.shape_variant, DiningTable.get_supported_variants_for_seat_count(10))
        second = apply_action(self.account, {'kind': 'table', 'data': {'name': 'Stol 2', 'hall': str(hall.pk), 'seat_count': 2}})
        session = TableSession.objects.create(restaurant=self.restaurant, hall=hall, table=table)
        TableSessionTable.objects.create(session=session, table=second)
        with self.assertRaises(ValidationError):
            apply_action(self.account, {'kind': 'table', 'pk': str(second.pk), 'data': {'is_active': False}})

    def test_preparation_station_foreign_scope_and_snapshot(self):
        foreign = PrepStation.objects.create(restaurant=self.other, name='Other kitchen')
        with self.assertRaises(Http404):
            apply_action(self.account, {'kind': 'category', 'pk': str(self.category.pk), 'data': {'prep_station': str(foreign.pk)}})
        station = PrepStation.objects.create(restaurant=self.restaurant, name='Kitchen')
        apply_action(self.account, {'kind': 'category', 'pk': str(self.category.pk), 'data': {'prep_station': str(station.pk)}})
        from apps.local_agents.sync import _menu_snapshot
        snapshot = _menu_snapshot(self.restaurant)
        self.assertIn(str(self.item.pk), str(snapshot))
        self.assertIn(str(station.pk), str(snapshot))
        apply_action(self.account, {'kind': 'item', 'pk': str(self.item.pk), 'data': {'is_stoplisted': True}})
        self.assertNotIn(str(self.item.pk), str(_menu_snapshot(self.restaurant)))

    def test_manual_creation_requires_confirmation_and_branch_paging(self):
        with patch('apps.catalog_assistant.bot.ManagementBotClient') as client:
            handler = ManagementBotHandler()
            handler.handle(self.callback('manual:' + str(self.category.pk)))
            handler.handle({'message': {'text': 'Choy | 5000', 'from': {'id': 123}, 'chat': {'type': 'private', 'id': 123}}})
            self.assertFalse(CatalogItem.objects.filter(name='Choy').exists())
            self.account.refresh_from_db()
            handler.handle(self.callback('confirm:' + self.account.state['nonce']))
            self.assertEqual(CatalogItem.objects.get(name='Choy').price, 5000)
            Restaurant.objects.bulk_create([Restaurant(name=f'Branch {index:02}') for index in range(15)])
            handler.handle(self.callback('home:0'))
            markup = client.return_value.send_message.call_args.kwargs['reply_markup']
            self.assertIn('home:1', str(markup))
            handler.handle(self.callback('home:1'))
            self.assertIn('home:0', str(client.return_value.send_message.call_args.kwargs['reply_markup']))

    def test_worker_failure_rolls_back_mutation_and_bounds_retries(self):
        update = ManagementBotUpdate.objects.create(update_id=23, payload={'message': {}})
        def failure(_):
            CatalogItem.objects.filter(pk=self.item.pk).update(price=999)
            raise TelegramAPIError('Transport failed')
        with patch('apps.catalog_assistant.bot.ManagementBotHandler.handle', side_effect=failure):
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    process_update(update.pk)
            process_update(update.pk)
        self.item.refresh_from_db()
        update.refresh_from_db()
        self.assertEqual(self.item.price, 100)
        self.assertEqual(update.status, 'rejected')
        self.assertEqual(update.attempts, 3)
        self.assertEqual(update.payload, {})

    def test_expired_callback_ack_does_not_block_action(self):
        with patch('apps.catalog_assistant.bot.ManagementBotClient') as client:
            client.return_value.answer_callback_query.side_effect = TelegramAPIError('expired', error_code=400)
            ManagementBotHandler().handle(self.callback('dashboard'))
            client.return_value.send_message.assert_called_once()
