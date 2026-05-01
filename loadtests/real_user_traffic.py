#!/usr/bin/env python
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import class_settings
import django
import requests
from class_settings import env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_BASE_URL = 'https://cafe-postcode.uz'
DEFAULT_FRONTEND_URLS = (
    'https://pos.cafe-postcode.uz/',
    'https://admin.cafe-postcode.uz/',
    'https://dashboard.cafe-postcode.uz/',
)


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        values = dict(attrs)
        candidate = values.get('src') or values.get('href')
        if candidate and re.search(r'\.(css|js)(\?|$)', candidate):
            self.assets.append(candidate)


class RealUserTrafficSmoke:
    def __init__(self):
        self.base_url = os.getenv('REAL_USER_BASE_URL', DEFAULT_BASE_URL).rstrip('/')
        self.frontend_urls = [
            url.strip()
            for url in os.getenv('REAL_USER_FRONTEND_URLS', ','.join(DEFAULT_FRONTEND_URLS)).split(',')
            if url.strip()
        ]
        self.pin = os.getenv('REAL_USER_PIN', '7391')
        self.username = f"realuser-smoke-{uuid.uuid4().hex[:10]}"
        self.display_prefix = f"real-user-smoke-{uuid.uuid4().hex[:8]}"
        self.results: list[dict[str, Any]] = []
        self.created_order_ids: list[str] = []
        self.user = None

        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                'Accept': 'application/json, text/html;q=0.9, */*;q=0.8',
                'User-Agent': 'PostcodeRealUserSmoke/1.0',
            }
        )

    def setup_django(self):
        env.read_env()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
        os.environ.setdefault('DJANGO_SETTINGS_CLASS', 'CoreSettings')
        class_settings.setup()
        django.setup()

    def record(self, name: str, ok: bool, status: int | None, elapsed_ms: int, detail: str = ''):
        self.results.append(
            {
                'name': name,
                'ok': ok,
                'status': status,
                'elapsed_ms': elapsed_ms,
                'detail': detail,
            }
        )

    def request(
        self,
        name: str,
        method: str,
        url: str,
        *,
        expected: tuple[int, ...] = (200,),
        **kwargs,
    ) -> requests.Response:
        started = time.perf_counter()
        response = self.session.request(method, url, timeout=20, **kwargs)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        ok = response.status_code in expected
        detail = ''
        if not ok:
            detail = response.text[:300].replace('\n', ' ')
        self.record(name, ok, response.status_code, elapsed_ms, detail)
        response.raise_for_status()
        if not ok:
            raise RuntimeError(f'{name} returned {response.status_code}: {detail}')
        return response

    @staticmethod
    def rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            data = payload.get('data') or payload.get('results')
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
        return []

    @staticmethod
    def first_menu_item_id(categories: list[dict[str, Any]]) -> str | None:
        for category in categories:
            for item in category.get('items') or []:
                item_id = item.get('id')
                if item_id:
                    return str(item_id)
        return None

    def create_temp_user(self):
        from apps.restaurants.models import Restaurant
        from apps.users.models import User

        restaurant = Restaurant.objects.filter(is_active=True).order_by('created_at').first()
        if restaurant is None:
            raise RuntimeError('No active restaurant found for real user traffic smoke test.')

        self.user = User.objects.create_superuser(
            username=self.username,
            password=uuid.uuid4().hex,
            full_name='Real User Smoke',
            restaurant=restaurant,
        )
        self.user.set_pin(self.pin)
        self.user.save(update_fields=['pin_code'])
        return restaurant

    def check_frontends(self):
        for frontend_url in self.frontend_urls:
            page = self.request(f'frontend page: {urlparse(frontend_url).netloc}', 'GET', frontend_url)
            parser = AssetParser()
            parser.feed(page.text)
            assets = []
            for asset in parser.assets:
                full_url = urljoin(frontend_url, asset)
                if urlparse(full_url).netloc == urlparse(frontend_url).netloc:
                    assets.append(full_url)
            for index, asset_url in enumerate(assets[:3], start=1):
                self.request(
                    f'frontend asset {index}: {urlparse(frontend_url).netloc}',
                    'GET',
                    asset_url,
                    expected=(200, 304),
                )

    def run_api_flow(self, restaurant):
        health = self.request('backend healthz', 'GET', f'{self.base_url}/healthz/')
        if health.headers.get('content-type', '').startswith('application/json'):
            health.json()

        login_response = self.request(
            'pos login by pin',
            'POST',
            f'{self.base_url}/api/v1/pos/auth/pin-login/',
            json={'restaurant_id': str(restaurant.id), 'pin': self.pin},
        )
        token = login_response.json().get('token')
        if not token:
            raise RuntimeError('PIN login did not return token.')
        self.session.headers.update({'Authorization': f'Token {token}'})

        self.request('pos auth me', 'GET', f'{self.base_url}/api/v1/pos/auth/me/')

        menu_response = self.request('pos catalog menu', 'GET', f'{self.base_url}/api/v1/pos/catalog/menu/')
        categories = self.rows(menu_response.json())
        item_id = self.first_menu_item_id(categories)
        if not item_id:
            raise RuntimeError('POS menu returned no active catalog items.')

        self.request('pos floor halls', 'GET', f'{self.base_url}/api/v1/pos/floor/halls/')
        self.request('pos cashier context', 'GET', f'{self.base_url}/api/v1/pos/billing/context/')
        self.request('pos open checks', 'GET', f'{self.base_url}/api/v1/pos/billing/open-checks/?status=open&limit=20')
        self.request('pos kitchen queue', 'GET', f'{self.base_url}/api/v1/pos/kitchen/queue/')

        order_response = self.request(
            'pos create takeaway order',
            'POST',
            f'{self.base_url}/api/v1/pos/sales/orders/',
            json={'channel': 'takeaway', 'guestCount': 1, 'displayName': self.display_prefix},
            expected=(201,),
        )
        order = order_response.json()
        order_id = str(order['id'])
        self.created_order_ids.append(order_id)

        self.request(
            'pos add order item',
            'POST',
            f'{self.base_url}/api/v1/pos/sales/orders/{order_id}/items/',
            json={'catalogItem': item_id, 'quantity': 1},
            expected=(201,),
        )
        self.request('pos submit order', 'POST', f'{self.base_url}/api/v1/pos/sales/orders/{order_id}/submit/')
        self.request('pos open checks after submit', 'GET', f'{self.base_url}/api/v1/pos/billing/open-checks/?status=open&limit=20')

    def cleanup(self):
        from apps.sales.models import Order
        from apps.users.models import User

        deleted_orders = 0
        if self.created_order_ids:
            deleted_orders = Order.objects.filter(id__in=self.created_order_ids).delete()[0]
        deleted_orders += Order.objects.filter(display_name__startswith=self.display_prefix).delete()[0]
        deleted_users = User.objects.filter(username=self.username).delete()[0]
        return {'deleted_orders': deleted_orders, 'deleted_users': deleted_users}

    def write_report(self, cleanup_result: dict[str, int]):
        payload = {
            'base_url': self.base_url,
            'frontend_urls': self.frontend_urls,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'ok': all(result['ok'] for result in self.results),
            'cleanup': cleanup_result,
            'results': self.results,
        }
        filename = f"real-user-traffic-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
        report_dir = Path(os.getenv('REAL_USER_REPORT_DIR', 'loadtests/reports'))
        try:
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / filename
            report_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        except PermissionError:
            report_dir = Path('/tmp/postcode-loadtest-reports')
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / filename
            report_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return report_path

    def run(self) -> int:
        self.setup_django()
        cleanup_result = {'deleted_orders': 0, 'deleted_users': 0}
        try:
            restaurant = self.create_temp_user()
            self.check_frontends()
            self.run_api_flow(restaurant)
            return_code = 0 if all(result['ok'] for result in self.results) else 1
        except Exception as exc:
            self.record('real user traffic smoke', False, None, 0, str(exc))
            return_code = 1
        finally:
            cleanup_result = self.cleanup()
            report_path = self.write_report(cleanup_result)

        print(f'Report: {report_path}')
        print(json.dumps({'ok': return_code == 0, 'cleanup': cleanup_result, 'results': self.results}, indent=2))
        return return_code


if __name__ == '__main__':
    sys.exit(RealUserTrafficSmoke().run())
