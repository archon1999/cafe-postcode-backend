import html
import re
import secrets
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, ValidationError
from .access import restaurants_for, require_access
from .bot_actions import apply_action, scoped_objects
from .bot_client import ManagementBotClient
from .drafts import create_draft, commit_draft
from .inputs import normalize_input
from .links import consume_link
from .models import CatalogDraft, ManagementBotAccount
from .mxik import search_mxik
from apps.restaurants.models import PrepStation
from common.sale_units import SALE_UNITS, sale_unit_label
from apps.telegram_reports.client import TelegramAPIError


def button(label, data):
    return {'text': label[:60], 'callback_data': data}


def safe(value):
    return html.escape(str(value)[:300])


def error_message(value):
    if isinstance(value, dict):
        return '; '.join(error_message(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return '; '.join(error_message(item) for item in value)
    return str(value)


class ManagementBotHandler:
    def __init__(self):
        self.client = ManagementBotClient()
        self.account = None

    def send(self, text, rows=()):
        if len(text) > 3900:
            # Truncate plain text before escaping, never cut an HTML entity/tag.
            text = html.escape(html.unescape(re.sub(r'<[^>]*>', '', text))[:3800])
        return self.client.send_message(chat_id=self.account.chat_id, text=text,
                                        reply_markup={'inline_keyboard': list(rows)})

    def state(self, **values):
        self.account.state = values
        self.account.save(update_fields=['state', 'updated_at'])

    def home(self, page=0):
        self.state()
        page = max(0, int(page))
        restaurants = restaurants_for(self.account.user).order_by('name')
        items = list(restaurants[page * 12:page * 12 + 13])
        rows = [[button(item.name, f'branch:{item.pk}')] for item in items[:12]]
        if page:
            rows.append([button('← Oldingi', f'home:{page-1}')])
        if len(items) > 12:
            rows.append([button('Keyingi →', f'home:{page+1}')])
        self.send('🏪 <b>Postcode boshqaruv</b>\nMenyu va zallarni boshqarish uchun shahobchani tanlang.',
                  rows)

    def dashboard(self):
        restaurant = require_access(self.account.user, self.account.restaurant_id, 'catalog_items', 'view')
        self.state()
        self.send(f'🏪 <b>{safe(restaurant.name)}</b>\nKerakli bo‘limni tanlang.', [
            [button('🍽 Menyu', 'list:category:0'), button('🏛 Zallar', 'list:zone:0')],
            [button('✨ AI orqali menyu kiritish', 'ai:')],
            [{'text': '🔎 MXIK qidirish', 'switch_inline_query_current_chat': ''}],
            [button('🔄 Shahobchani almashtirish', 'home')],
        ])

    def handle(self, update):
        if 'inline_query' in update:
            return self.inline(update['inline_query'])
        callback = update.get('callback_query')
        message = (callback or {}).get('message') or update.get('message') or {}
        sender = (callback or message).get('from') or {}
        chat = message.get('chat') or {}
        if chat.get('type') != 'private' or not sender.get('id'):
            return
        if callback:
            try:
                self.client.answer_callback_query(callback['id'])
            except TelegramAPIError as error:
                if error.error_code != 400:  # Delayed queue callbacks can expire.
                    raise
        text = str(message.get('text') or message.get('caption') or '').strip()
        try:
            if not callback and text.startswith('/start '):
                self.account = consume_link(text.split(maxsplit=1)[1], sender['id'], chat['id'])
                return self.home()
            self.account = ManagementBotAccount.objects.select_for_update().select_related('user').filter(telegram_user_id=sender['id']).first()
            if not self.account:
                self.client.send_message(chat_id=chat['id'], text='🔐 Admin panel → Katalog → “Telegram orqali boshqarish” orqali shaxsiy havola oling.')
                return
            if text == '/disconnect':
                self.account.delete()
                self.client.send_message(chat_id=chat['id'], text='Telegram ulanishi uzildi. Qayta ulash uchun admin paneldan yangi havola oling.')
                return
            if not restaurants_for(self.account.user).exists():
                raise ValidationError('Shahobcha boshqaruvi uchun ruxsatingiz hozir mavjud emas.')
            if callback:
                return self.callback(str(callback.get('data') or ''))
            if text in ('/start', '/menu', '/cancel', '/help'):
                return self.home() if not self.account.restaurant_id else self.dashboard()
            return self.message(text, message)
        except (APIException, Http404, ValueError, KeyError, IndexError) as error:
            detail = getattr(error, 'detail', 'Obyekt topilmadi yoki unga ruxsat yo‘q.')
            self.client.send_message(chat_id=chat['id'], text='⚠️ ' + safe(error_message(detail))[:3500] + '\n/cancel — bosh menyu')

    def inline(self, query):
        account = ManagementBotAccount.objects.select_related('user').filter(telegram_user_id=query['from']['id']).first()
        rows = []
        if account and restaurants_for(account.user).exists():
            try:
                rows = search_mxik(query.get('query', ''))
            except APIException:
                pass
        self.client.call('answerInlineQuery', {'inline_query_id': query['id'], 'is_personal': True, 'cache_time': 0,
            'results': [{'type': 'article', 'id': row['code'], 'title': row['name'] or row['code'],
                         'description': row['code'], 'input_message_content': {'message_text': f"MXIK: {row['code']}\n{row['name']}"}}
                        for row in rows]})

    def listing(self, kind, page=0, parent=''):
        objects = scoped_objects(self.account.user, self.account.restaurant_id, kind)
        if parent and kind == 'item':
            objects = objects.filter(category_id=parent)
        elif parent and kind == 'hall':
            objects = objects.filter(zone_or_cabin_id=parent)
        elif parent and kind == 'table':
            objects = objects.filter(hall_id=parent)
        page = max(0, min(int(page), 10000))
        items = list(objects.order_by('name')[page * 8:page * 8 + 9])
        rows = [[button(('🟢 ' if getattr(obj, 'is_active', True) else '⚪ ') + obj.name, f'view:{kind}:{obj.pk}')]
                for obj in items[:8]]
        # Store parent for short callback payloads (<64 bytes).
        self.state(list_kind=kind, parent=parent)
        if page:
            rows.append([button('← Oldingi', f'page:{kind}:{page-1}')])
        if len(items) > 8:
            rows.append([button('Keyingi →', f'page:{kind}:{page+1}')])
        rows += [[button('➕ Qo‘shish', f'new:{kind}')], [button('🏠 Bosh menyu', 'dashboard')]]
        self.send({'category': '🍽 Kategoriyalar', 'item': '🍴 Mahsulotlar', 'zone': '📍 Hududlar', 'hall': '🏛 Zallar', 'table': '🪑 Stollar'}[kind], rows)

    def detail(self, kind, pk):
        obj = get_object_or_404(scoped_objects(self.account.user, self.account.restaurant_id, kind), pk=pk)
        self.state(kind=kind, pk=pk)
        rows = [[button('✏️ Nomini o‘zgartirish', 'edit:name')]]
        info = f'<b>{safe(obj.name)}</b>'
        if kind == 'category':
            info += f'\nMXIK: {safe(obj.mxik_code)}'
            info += f'\nTayyorlash joyi: {safe(obj.prep_station.name) if obj.prep_station_id else "❗ tanlanmagan"}'
            rows.insert(0, [button('🍴 Mahsulotlar', f'children:item:{pk}')])
            rows.append([button('🔎 MXIKni almashtirish', 'edit:mxik_code')])
            rows.append([button('👨‍🍳 Tayyorlash joyi', 'choose:prep_station:0')])
        elif kind == 'item':
            info += f'\n{obj.price:,} so‘m · {safe(obj.sale_unit)}\n' + ('⛔ Stop-listda' if obj.is_stoplisted else '✅ Sotuvda')
            rows += [[button('💰 Narx', 'edit:price'), button('▶️ Sotuvga qaytarish' if obj.is_stoplisted else '⛔ Stop-list', 'toggle:is_stoplisted')]]
            rows.append([button('📁 Kategoriya', 'choose:category:0'), button('⚖️ O‘lchov birligi', 'choose:sale_unit:0')])
        elif kind == 'zone':
            rows.insert(0, [button('🏛 Zallar', f'children:hall:{pk}')])
        elif kind == 'hall':
            rows.insert(0, [button('🪑 Stollar', f'children:table:{pk}')])
        elif kind == 'table':
            info += f'\nO‘rindiqlar: {obj.seat_count}'
            rows.append([button('🪑 O‘rindiq soni', 'edit:seat_count')])
        rows += [[button('Faollashtirish' if not obj.is_active else 'Yashirish', 'toggle:is_active')], [button('🏠 Bosh menyu', 'dashboard')]]
        self.send(info, rows)

    def confirm(self, pending, summary):
        nonce = secrets.token_hex(8)
        self.state(pending=pending, nonce=nonce)
        self.send('📝 <b>O‘zgarishni tekshiring</b>\n' + safe(summary), [
            [button('✅ Saqlash', f'confirm:{nonce}'), button('Bekor qilish', 'dashboard')],
        ])

    def callback(self, value):
        parts = value.split(':')
        command = parts[0]
        if command == 'home':
            return self.home(parts[1] if len(parts) > 1 else 0)
        if command == 'branch' and len(parts) == 2:
            self.account.restaurant = require_access(self.account.user, parts[1], 'catalog_items', 'view')
            self.account.save(update_fields=['restaurant', 'updated_at'])
            return self.dashboard()
        if not self.account.restaurant_id:
            return self.home()
        require_access(self.account.user, self.account.restaurant_id, 'catalog_items', 'view')
        state = self.account.state
        if command == 'dashboard':
            return self.dashboard()
        if command in ('list', 'page') and len(parts) == 3:
            return self.listing(parts[1], parts[2], state.get('parent', '') if command == 'page' else '')
        if command == 'children' and len(parts) == 3:
            return self.listing(parts[1], 0, parts[2])
        if command == 'view' and len(parts) == 3:
            return self.detail(parts[1], parts[2])
        if command == 'choose' and len(parts) == 3 and state.get('kind'):
            return self.choices(parts[1], int(parts[2]))
        if command == 'pick' and len(parts) == 3 and state.get('kind'):
            field, value = parts[1:]
            if field == 'sale_unit' and state['kind'] == 'item' and value in SALE_UNITS:
                label = sale_unit_label(value)
            elif field == 'category' and state['kind'] == 'item':
                label = get_object_or_404(scoped_objects(self.account.user, self.account.restaurant_id, 'category'), pk=value).name
            elif field == 'prep_station' and state['kind'] == 'category':
                label = get_object_or_404(PrepStation, restaurant_id=self.account.restaurant_id, pk=value, is_active=True).name
            else:
                raise ValidationError('Tanlov eskirgan. Qaytadan tanlang.')
            obj = get_object_or_404(scoped_objects(self.account.user, self.account.restaurant_id, state['kind']), pk=state['pk'])
            return self.confirm({'kind': state['kind'], 'pk': state['pk'], 'data': {field: value}}, f'{obj.name} → {label}')
        if command == 'ai' and len(parts) == 2:
            self.state(input='ai', category_id=parts[1] or None)
            return self.send('✨ Menyu rasmini, Excel faylini yoki matnini yuboring.\nMasalan: Osh 35 ming, choy 5 ming.\nAI draft tayyorlaydi, saqlashdan oldin tekshirasiz.')
        if command == 'new':
            kind = parts[1]
            scoped_objects(self.account.user, self.account.restaurant_id, kind, 'create')
            if kind == 'item':
                parent = state.get('parent', '')
                return self.send('Mahsulotni qanday kiritamiz?', [[button('✨ AI: matn, rasm yoki Excel', 'ai:' + parent)],
                    [button('✏️ Nom va narxni kiritish', 'manual:' + parent)]])
            parent = state.get('parent', '')
            if kind in ('hall', 'table') and not parent:
                raise ValidationError('Avval hududni yoki zalni tanlang.')
            self.state(input='new', kind=kind, parent=parent)
            return self.send({'category': 'Yangi kategoriya nomini yuboring. Keyin MXIK tanlaysiz.',
                              'zone': 'Yangi hudud nomini yuboring.', 'hall': 'Yangi zal nomini yuboring.',
                              'table': 'Stol nomi va o‘rindiq sonini yuboring.\nMasalan: Stol 5 | 4'}[kind])
        if command == 'manual' and len(parts) == 2:
            category = get_object_or_404(scoped_objects(self.account.user, self.account.restaurant_id, 'category'), pk=parts[1])
            self.state(input='manual_item', category_id=str(category.pk))
            return self.send('Mahsulot nomi va narxini yuboring.\nMasalan: <code>Osh | 35000</code>\nO‘lchov birligini keyin o‘zgartirishingiz mumkin.')
        if command == 'edit' and state.get('kind'):
            self.state(**{**state, 'input': 'edit', 'field': parts[1]})
            rows = [[{'text': '🔎 MXIK qidirish', 'switch_inline_query_current_chat': ''}]] if parts[1] == 'mxik_code' else []
            return self.send('Yangi qiymatni yuboring.', rows)
        if command == 'toggle' and state.get('kind'):
            field = parts[1]
            if field not in ('is_active', 'is_stoplisted'):
                return
            obj = get_object_or_404(scoped_objects(self.account.user, self.account.restaurant_id, state['kind'], 'update'), pk=state['pk'])
            pending = {'kind': state['kind'], 'pk': state['pk'], 'data': {field: not getattr(obj, field)}}
            label = ('Faollashtirish' if not obj.is_active else 'Yashirish') if field == 'is_active' else ('Sotuvga qaytarish' if obj.is_stoplisted else 'Stop-listga qo‘shish')
            return self.confirm(pending, f'{obj.name}: {label}')
        if command == 'confirm' and secrets.compare_digest(parts[-1], state.get('nonce', '')) and state.get('pending'):
            obj = apply_action(self.account, state['pending'])
            kind = state['pending']['kind']
            self.state()
            self.send('✅ Saqlandi. POS sinxronlashuvi so‘raldi.')
            return self.detail(kind, str(obj.pk))
        if command == 'draft' and len(parts) == 3:
            return self.review(parts[1], int(parts[2]))
        if command == 'draftsave' and state.get('draft_id') and secrets.compare_digest(parts[-1], state.get('nonce', '')):
            draft = get_object_or_404(CatalogDraft, pk=state['draft_id'], owner=self.account.user, restaurant_id=self.account.restaurant_id)
            result = commit_draft(self.account.user, draft.pk, draft.rows, draft.revision)
            self.state()
            return self.send(f'✅ {result.result["count"]} ta mahsulot saqlandi.', [[button('🍽 Menyu', 'list:category:0')]])
        self.send('Bu tugma eskirgan. /menu orqali davom eting.')

    def message(self, text, message):
        state = self.account.state
        if state.get('input') == 'manual_item':
            fields = [part.strip() for part in text.split('|')]
            if len(fields) != 2 or not fields[0] or not fields[1].replace(' ', '').isdigit():
                raise ValidationError('Masalan: Osh | 35000')
            return self.confirm({'kind': 'item', 'data': {'name': fields[0], 'name_uz': fields[0],
                'price': int(fields[1].replace(' ', '')), 'category': state['category_id'], 'sale_unit': 'piece'}}, text)
        if state.get('input') == 'ai':
            files = []
            if message.get('photo'):
                files.append(self.client.download(message['photo'][-1]['file_id']))
            elif message.get('document'):
                doc = message['document']
                files.append(self.client.download(doc['file_id'], doc.get('file_name', 'file')))
            self.send('⏳ Menyu o‘qilmoqda. Draft tayyor bo‘lgach tekshirish uchun yuboraman.')
            draft = create_draft(self.account.user, self.account.restaurant_id, normalize_input(text, files), state.get('category_id'))
            return self.review(str(draft.pk))
        if state.get('input') == 'category_mxik':
            code = self.mxik_code(text)
            return self.confirm({'kind': 'category', 'data': {'name': state['name'], 'name_uz': state['name'], 'mxik_code': code}}, f'{state["name"]}\nMXIK: {code}')
        if state.get('input') == 'new':
            kind = state['kind']
            if not text or len(text) > 255:
                raise ValidationError('Nomni 1–255 belgi bilan kiriting.')
            if kind == 'category':
                self.state(input='category_mxik', name=text)
                return self.send('MXIK kodini tanlang yoki 17 raqamli kod yuboring.', [[{'text': '🔎 MXIK qidirish', 'switch_inline_query_current_chat': text}]])
            data = {'name': text}
            if kind == 'hall':
                data['zone_or_cabin_id'] = state['parent']
            if kind == 'table':
                fields = text.split('|')
                if len(fields) != 2 or not fields[1].strip().isdigit():
                    raise ValidationError('Masalan: Stol 5 | 4')
                data = {'name': fields[0].strip(), 'seat_count': int(fields[1]), 'hall': state['parent']}
            return self.confirm({'kind': kind, 'data': data}, text)
        if state.get('input') == 'edit':
            field = state['field']
            value = text
            if field in ('price', 'seat_count'):
                value = text.replace(' ', '')
                if not value.isdigit():
                    raise ValidationError('Butun son kiriting. Masalan: 35000')
                value = int(value)
            if field == 'mxik_code':
                value = self.mxik_code(text)
            data = {field: value}
            if field == 'name' and state['kind'] in ('category', 'item'):
                data['name_uz'] = value
            obj = get_object_or_404(scoped_objects(self.account.user, self.account.restaurant_id, state['kind']), pk=state['pk'])
            labels = {'name': 'Nomi', 'price': 'Narxi', 'seat_count': 'O‘rindiqlar', 'mxik_code': 'MXIK'}
            return self.confirm({'kind': state['kind'], 'pk': state['pk'], 'data': data}, f'{obj.name}\n{labels.get(field, field)}: {text}')
        if state.get('draft_id'):
            return self.edit_draft(text)
        return self.send('Amalni tugmalar orqali tanlang. /menu — bosh menyu.')

    @staticmethod
    def mxik_code(text):
        match = re.search(r'(?<!\d)\d{17}(?!\d)', text)
        if not match:
            raise ValidationError('17 raqamli MXIK kodini yuboring.')
        return match.group()

    def review(self, draft_id, page=0):
        draft = get_object_or_404(CatalogDraft, pk=draft_id, owner=self.account.user, restaurant_id=self.account.restaurant_id)
        require_access(self.account.user, draft.restaurant_id)
        page = max(0, min(page, (len(draft.rows) - 1) // 6))
        nonce = secrets.token_hex(8)
        self.state(draft_id=str(draft.pk), nonce=nonce)
        lines = ['📝 <b>Menyu drafti</b>']
        for index, row in enumerate(draft.rows[page * 6:page * 6 + 6], page * 6):
            lines.append(f'{index+1}. {safe(row["name"])} — {row["price"] if row["price"] is not None else "❗ narx yo‘q"} so‘m\n'
                         f'   {safe(row["category_name"] or "❗ kategoriya yo‘q")} · {safe(row["sale_unit"])}' +
                         ('\n   ⚠️ ' + safe(row['warning'][:100]) if row.get('warning') else '') +
                         ('\n   ⏭ O‘tkazib yuboriladi' if not row.get('selected', True) else ''))
        lines.append('\nTuzatish: <code>1 | Osh | 35000 | Taomlar</code>\nQatorni chiqarish: <code>skip 1</code>\nQaytarish: <code>include 1</code>\nYangi kategoriyani avval Menyu bo‘limida MXIK bilan yarating.')
        rows = []
        if page:
            rows.append([button('← Oldingi', f'draft:{draft.pk}:{page-1}')])
        if (page + 1) * 6 < len(draft.rows):
            rows.append([button('Keyingi →', f'draft:{draft.pk}:{page+1}')])
        rows += [[button('✅ Tanlanganlarini saqlash', f'draftsave:{nonce}')], [button('Bekor qilish', 'dashboard')]]
        return self.send('\n'.join(lines), rows)

    def choices(self, field, page=0):
        state = self.account.state
        page = max(0, page)
        if field == 'sale_unit' and state['kind'] == 'item':
            options = [(key, sale_unit_label(key)) for key in SALE_UNITS]
        elif field == 'category' and state['kind'] == 'item':
            options = list(scoped_objects(self.account.user, self.account.restaurant_id, 'category').filter(is_active=True).order_by('name').values_list('pk', 'name'))
        elif field == 'prep_station' and state['kind'] == 'category':
            options = list(PrepStation.objects.filter(restaurant_id=self.account.restaurant_id, is_active=True).order_by('name').values_list('pk', 'name'))
        else:
            raise ValidationError('Tanlov topilmadi.')
        rows = [[button(name, f'pick:{field}:{pk}')] for pk, name in options[page * 8:page * 8 + 8]]
        if page:
            rows.append([button('← Oldingi', f'choose:{field}:{page-1}')])
        if (page + 1) * 8 < len(options):
            rows.append([button('Keyingi →', f'choose:{field}:{page+1}')])
        rows.append([button('← Orqaga', f'view:{state["kind"]}:{state["pk"]}')])
        return self.send('Kerakli qiymatni tanlang.' if options else 'Hali sozlanmagan. Admin panelda yarating.', rows)

    @transaction.atomic
    def edit_draft(self, text):
        draft = get_object_or_404(CatalogDraft.objects.select_for_update(), pk=self.account.state['draft_id'], owner=self.account.user, restaurant_id=self.account.restaurant_id, committed_at__isnull=True)
        require_access(self.account.user, draft.restaurant_id)
        match = re.fullmatch(r'(skip|include)\s+(\d+)', text)
        parts = [part.strip() for part in text.split('|')]
        if match:
            index = int(match[2]) - 1
        elif len(parts) == 4 and parts[0].isdigit() and parts[2].replace(' ', '').isdigit():
            index = int(parts[0]) - 1
        else:
            raise ValidationError('Format: 1 | Osh | 35000 | Taomlar yoki skip 1')
        if not 0 <= index < len(draft.rows):
            raise ValidationError('Qator raqami topilmadi.')
        if match:
            draft.rows[index]['selected'] = match[1] == 'include'
        else:
            category = scoped_objects(self.account.user, draft.restaurant_id, 'category').filter(name__iexact=parts[3], is_active=True).first()
            if category is None:
                raise ValidationError('Kategoriya topilmadi. Mavjud kategoriya nomini kiriting.')
            draft.rows[index].update(name=parts[1], price=int(parts[2].replace(' ', '')), category_id=str(category.pk), category_name=category.name)
        draft.revision += 1
        draft.save(update_fields=['rows', 'revision', 'updated_at'])
        return self.review(str(draft.pk), index // 6)
