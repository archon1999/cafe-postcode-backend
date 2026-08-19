import os
import random
import uuid

import urllib3
from locust import HttpUser, between, task


API_PREFIX = '/api/v1'
RESTAURANT_ID = os.getenv('LOCUST_RESTAURANT_ID', '').strip()
PIN = os.getenv('LOCUST_PIN', '').strip()
TOKEN = os.getenv('LOCUST_TOKEN', '').strip()
TOKEN_POOL = [
    tuple(item.split(':', 1))
    for item in os.getenv('LOCUST_TOKEN_POOL', '').split(',')
    if ':' in item
]
ENABLE_PAYMENTS = os.getenv('LOCUST_ENABLE_PAYMENTS', '0').strip().lower() in {'1', 'true', 'yes', 'on'}
VERIFY_TLS = os.getenv('LOCUST_VERIFY_TLS', '1').strip().lower() not in {'0', 'false', 'no', 'off'}
if not VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def first_payload_rows(payload):
    if isinstance(payload, dict):
        rows = payload.get('data')
        if isinstance(rows, list):
            return rows
    if isinstance(payload, list):
        return payload
    return []


def find_nested_ids(rows, key):
    values = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get(key)
        if value:
            values.append(value)
        for nested_value in row.values():
            if isinstance(nested_value, list):
                values.extend(find_nested_ids(nested_value, key))
    return values


class PosApiUser(HttpUser):
    wait_time = between(0.2, 1.2)

    def on_start(self):
        self.client.verify = VERIFY_TLS
        self.restaurant_id = RESTAURANT_ID
        self.catalog_item_ids = []
        self.table_ids = []
        self.floor_available = True

        if TOKEN_POOL:
            self.restaurant_id, token = random.choice(TOKEN_POOL)
            self.client.headers.update({'Authorization': f'Token {token}'})
            self.refresh_menu()
            self.refresh_halls()
            return

        if TOKEN:
            self.client.headers.update({'Authorization': f'Token {TOKEN}'})
            self.refresh_menu()
            self.refresh_halls()
            return

        if self.restaurant_id and PIN:
            response = self.client.post(
                f'{API_PREFIX}/pos/auth/pin-login/',
                json={'restaurantId': self.restaurant_id, 'pin': PIN},
                name='pos auth: pin-login',
            )
            if response.ok:
                token = response.json().get('token')
                if token:
                    self.client.headers.update({'Authorization': f'Token {token}'})

        self.refresh_menu()
        self.refresh_halls()

    @task(20)
    def refresh_menu(self):
        response = self.client.get(f'{API_PREFIX}/pos/catalog/menu/', name='pos catalog: menu')
        if response.ok:
            rows = first_payload_rows(response.json())
            self.catalog_item_ids = find_nested_ids(rows, 'id') if not self.catalog_item_ids else self.catalog_item_ids
            item_ids = []
            for category in rows:
                item_ids.extend(find_nested_ids(category.get('items', []), 'id') if isinstance(category, dict) else [])
            if item_ids:
                self.catalog_item_ids = item_ids

    @task(12)
    def refresh_halls(self):
        if not self.floor_available:
            return
        with self.client.get(f'{API_PREFIX}/pos/floor/halls/', name='pos floor: halls', catch_response=True) as response:
            if response.ok:
                self.table_ids = find_nested_ids(first_payload_rows(response.json()), 'id')
            elif response.status_code == 400:
                self.floor_available = False
                response.success()

    @task(10)
    def open_checks(self):
        self.client.get(f'{API_PREFIX}/pos/billing/open-checks/', name='pos billing: open checks')

    @task(10)
    def kitchen_queue(self):
        self.client.get(f'{API_PREFIX}/pos/kitchen/queue/', name='pos kitchen: queue')

    @task(6)
    def create_takeaway_order_flow(self):
        if not self.catalog_item_ids:
            self.refresh_menu()
        if not self.catalog_item_ids:
            return

        order_response = self.client.post(
            f'{API_PREFIX}/pos/sales/orders/',
            json={
                'channel': 'takeaway',
                'guestCount': 1,
                'displayName': f'load-{uuid.uuid4().hex[:8]}',
            },
            name='pos sales: create takeaway order',
        )
        if not order_response.ok:
            return

        order = order_response.json()
        order_id = order.get('id')
        item_id = random.choice(self.catalog_item_ids)
        item_response = self.client.post(
            f'{API_PREFIX}/pos/sales/orders/{order_id}/items/',
            json={'catalogItem': item_id, 'quantity': random.randint(1, 3)},
            name='pos sales: add order item',
        )
        if not item_response.ok:
            return

        submit_response = self.client.post(
            f'{API_PREFIX}/pos/sales/orders/{order_id}/submit/',
            name='pos sales: submit order',
        )
        if ENABLE_PAYMENTS and submit_response.ok:
            submitted_order = submit_response.json()
            amount = submitted_order.get('total') or submitted_order.get('subtotal') or 1
            self.client.post(
                f'{API_PREFIX}/pos/billing/orders/{order_id}/pay/',
                json={'method': 'cash', 'amount': amount},
                name='pos billing: pay order',
            )

    @task(2)
    def table_sessions_read(self):
        if not self.floor_available:
            return
        self.client.get(f'{API_PREFIX}/pos/floor/table-sessions/?status=open', name='pos floor: table sessions')
