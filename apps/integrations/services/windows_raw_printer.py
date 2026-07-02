import base64
import ctypes
import os
import socket
from ctypes import wintypes

from django.utils import timezone

from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError


class DOCINFO(ctypes.Structure):
    _fields_ = [
        ('pDocName', wintypes.LPWSTR),
        ('pOutputFile', wintypes.LPWSTR),
        ('pDatatype', wintypes.LPWSTR),
    ]


class WindowsRawPrinterIntegrationService:
    def __init__(self, config):
        self.config = config
        self.settings = dict(getattr(config, 'settings', {}) or {})

    @staticmethod
    def _encoding_from_settings(settings: dict) -> str:
        return str(settings.get('encoding') or settings.get('charset') or 'cp866').strip() or 'cp866'

    @staticmethod
    def _format_money(value) -> str:
        return f"{int(value or 0):,}".replace(',', ' ')

    @staticmethod
    def _safe_text(value, *, encoding: str) -> str:
        text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
        text = WindowsRawPrinterIntegrationService._normalize_text_for_encoding(text, encoding=encoding)
        return text.encode(encoding, errors='replace').decode(encoding, errors='replace')

    @staticmethod
    def _normalize_text_for_encoding(value: str, *, encoding: str) -> str:
        if encoding.lower().replace('_', '-').replace('windows-', 'cp') not in {'cp1251', 'cp866'}:
            return value
        return value.translate(
            str.maketrans(
                {
                    'Қ': 'К',
                    'қ': 'к',
                    'Ғ': 'Г',
                    'ғ': 'г',
                    'Ҳ': 'Х',
                    'ҳ': 'х',
                    'Ў': 'У',
                    'ў': 'у',
                    'ʼ': "'",
                    '‘': "'",
                    '’': "'",
                    '“': '"',
                    '”': '"',
                    '–': '-',
                    '—': '-',
                }
            )
        )

    @staticmethod
    def _escpos_code_page_command(encoding: str, code_page) -> bytes:
        try:
            if code_page is not None:
                code_page_number = int(code_page)
                if 0 <= code_page_number <= 255:
                    return bytes([0x1B, 0x74, code_page_number])
        except (TypeError, ValueError):
            pass

        normalized = encoding.lower().replace('_', '-').replace('windows-', 'cp')
        mapping = {
            'cp437': 0,
            'ibm437': 0,
            'cp850': 2,
            'ibm850': 2,
            'cp866': 18,
            'ibm866': 18,
            'cp1251': 46,
            'cp1252': 16,
        }
        selected = mapping.get(normalized)
        return bytes([0x1B, 0x74, selected]) if selected is not None else b''

    @staticmethod
    def _chars_per_line(paper_width_mm: int) -> int:
        return 42 if paper_width_mm >= 80 else 32

    @staticmethod
    def _pad_line(left: str, right: str, *, width: int) -> str:
        left = left.rstrip()
        right = right.rstrip()
        available = max(width - len(right) - 1, 0)
        if len(left) > available:
            left = left[:available]
        spaces = max(width - len(left) - len(right), 1)
        return f'{left}{" " * spaces}{right}'

    @staticmethod
    def _center(value: str, *, width: int) -> str:
        text = value.strip()
        if len(text) >= width:
            return text
        return f'{" " * ((width - len(text)) // 2)}{text}'

    @staticmethod
    def _date_time_parts(value) -> tuple[str, str]:
        text = str(value or '').strip().replace('T', ' ')
        if not text:
            return '', ''
        date, _, rest = text.partition(' ')
        if len(date) == 10 and date[4] == '-' and date[7] == '-':
            date = f'{date[8:10]}.{date[5:7]}.{date[0:4]}'
        return date, rest[:8]

    @staticmethod
    def _social_line(value: str) -> str:
        text = str(value or '').strip()
        if not text:
            return ''
        if ':' in text:
            return text
        lowered = text.lower()
        if 'instagram' in lowered or lowered.startswith('insta') or lowered.startswith('@'):
            return f'Instagram: {text}'
        if 'telegram' in lowered or lowered.startswith('tg'):
            return f'Telegram: {text}'
        return f'Social: {text}'

    def _item_line(self, name: str, quantity: int, amount, *, width: int) -> str:
        amount_text = self._format_money(amount) if amount not in (None, '') else ''
        quantity_text = f'x{quantity}'
        right_start = width - len(amount_text)
        left_limit = max(min(22, right_start - len(quantity_text) - 2), 8)
        left = name[:left_limit]
        middle_start = min(max(24, len(left) + 1), max(right_start - len(quantity_text) - 1, len(left) + 1))
        chars = [' '] * width
        chars[: len(left)] = left
        chars[middle_start : middle_start + len(quantity_text)] = quantity_text
        if amount_text:
            chars[right_start : right_start + len(amount_text)] = amount_text
        return ''.join(chars).rstrip()

    @staticmethod
    def _order_label(payload: dict) -> str:
        label = str(payload.get('order_label') or '').strip()
        if label:
            return label
        return f"#{int(payload.get('order_number') or 0)}"

    def _build_lines(self, payload: dict) -> list[str]:
        encoding = self._encoding_from_settings(self.settings)
        paper_width_mm = int(self.settings.get('paper_width_mm') or 80)
        width = self._chars_per_line(paper_width_mm)
        separator = '-' * width
        date, time = self._date_time_parts(payload.get('printed_at_label'))
        restaurant_name = self._safe_text(payload.get('restaurant_name') or '', encoding=encoding)
        restaurant_address = self._safe_text(payload.get('restaurant_address') or '', encoding=encoding)
        restaurant_phone = self._safe_text(payload.get('restaurant_phone') or '', encoding=encoding)
        restaurant_social = self._safe_text(self._social_line(payload.get('restaurant_social') or ''), encoding=encoding)
        order_number = str(self._order_label(payload)).lstrip('#')
        channel_label = self._safe_text(payload.get('channel_label') or '', encoding=encoding)

        if payload.get('kitchen_ticket'):
            lines = [
                self._center(restaurant_name.upper(), width=width),
                separator,
                self._center(self._safe_text(f'Buyurtma raqami: {order_number}', encoding=encoding), width=width),
                separator,
            ]
            if date:
                lines.append(f'Sana: {date}')
            if time:
                lines.append(f'Buyurtma vaqti: {time}')
            lines.append(f'Buyurtma turi: {channel_label}')
            table_label = payload.get('table_label')
            if table_label:
                lines.append(self._safe_text(table_label, encoding=encoding))
            delivery_phone = self._safe_text(payload.get('delivery_phone') or '', encoding=encoding)
            delivery_address = self._safe_text(payload.get('delivery_address') or '', encoding=encoding)
            if delivery_phone:
                lines.append(f'Mijoz tel: {delivery_phone}')
            if delivery_address:
                lines.append(f'Mijoz manzil: {delivery_address[: max(width - 14, 0)]}')
            lines.append(separator)
            for item in payload.get('items', []):
                item_name = self._safe_text(item.get('name', ''), encoding=encoding)
                quantity = int(item.get('quantity') or 0)
                lines.append(self._item_line(item_name, quantity, item.get('line_total'), width=width))
                item_note = self._safe_text(item.get('note') or '', encoding=encoding)
                if item_note:
                    lines.append(f'  {item_note[: max(width - 2, 0)]}')
                lines.append(separator)
            if payload.get('total') not in (None, ''):
                lines.append(self._pad_line('Jami:', self._format_money(payload.get('total')), width=width))
            order_note = self._safe_text(payload.get('order_note') or '', encoding=encoding)
            if order_note:
                lines.extend([separator, f'Izoh: {order_note[: max(width - 6, 0)]}'])
            lines.extend([separator, self._center('Buyurtmangiz uchun raxmat!', width=width), self._center('Yoqimli ishtaha!', width=width), ''])
            return lines

        lines = [
            self._center(restaurant_name.upper(), width=width),
            separator,
            self._center(self._safe_text(f'Buyurtma raqami: {order_number}', encoding=encoding), width=width),
            separator,
        ]

        if restaurant_address:
            lines.append(f'Manzil: {restaurant_address[: max(width - 8, 0)]}')
        if restaurant_phone:
            lines.append(f'Tel: {restaurant_phone}')
        if restaurant_social:
            lines.append(restaurant_social[:width])
        lines.append(separator)
        if date:
            lines.append(f'Sana: {date}')
        if time:
            lines.append(f'Buyurtma vaqti: {time}')
        lines.append(f'Buyurtma turi: {channel_label}')

        table_label = payload.get('table_label')
        if table_label:
            lines.append(self._safe_text(table_label, encoding=encoding))

        waiter_name = payload.get('waiter_name')
        if waiter_name:
            lines.append(self._safe_text(f'Ofitsiant: {waiter_name}', encoding=encoding))

        lines.append(separator)

        for item in payload.get('items', []):
            item_name = self._safe_text(item.get('name', ''), encoding=encoding)
            quantity = int(item.get('quantity') or 0)
            lines.append(self._item_line(item_name, quantity, item.get('line_total'), width=width))
            item_note = self._safe_text(item.get('note') or '', encoding=encoding)
            if item_note:
                lines.append(f'  {item_note[: max(width - 2, 0)]}')
            lines.append(separator)

        lines.extend(
            [
                self._pad_line('Mahsulotlar narxi', self._format_money(payload.get('subtotal')), width=width),
                self._pad_line('Xizmat narxi', self._format_money(payload.get('service_fee')), width=width),
                self._pad_line('Jami:', self._format_money(payload.get('total')), width=width),
            ]
        )

        order_note = self._safe_text(payload.get('order_note') or '', encoding=encoding)
        if order_note:
            lines.extend([separator, f'Izoh: {order_note[: max(width - 6, 0)]}'])

        lines.extend([separator, self._center('Buyurtmangiz uchun raxmat!', width=width), self._center('Yoqimli ishtaha!', width=width), ''])
        return lines

    def _build_bytes(self, payload: dict) -> bytes:
        encoding = self._encoding_from_settings(self.settings)
        feed_lines_before_cut = int(self.settings.get('feed_lines_before_cut') or 6)
        body = '\n'.join(self._build_lines(payload))
        esc = bytes([0x1B])
        gs = bytes([0x1D])
        print_mode = esc + b'!' + bytes([0x00])
        content = b''.join(
            [
                esc + b'@',
                self._escpos_code_page_command(encoding, self.settings.get('code_page')),
                print_mode,
                body.encode(encoding, errors='replace'),
                esc + b'!' + bytes([0x00]),
            ]
        )
        if feed_lines_before_cut > 0:
            content += esc + b'd' + bytes([min(feed_lines_before_cut, 10)])
        if self.settings.get('cut_after_print', True):
            content += gs + b'V' + bytes([0])
        return content

    @staticmethod
    def _escpos_qr_code(value: str) -> bytes:
        data = value.encode('utf-8')
        if not data:
            return b''

        def store_command(command_data: bytes) -> bytes:
            length = len(command_data) + 3
            return b'\x1d(k' + bytes([length & 0xFF, (length >> 8) & 0xFF, 49]) + command_data

        return b''.join(
            [
                b'\n',
                store_command(b'\x41\x32\x00'),
                store_command(b'\x43\x06'),
                store_command(b'\x45\x31'),
                store_command(b'\x50\x30' + data),
                store_command(b'\x51\x30'),
                b'\n',
            ]
        )

    def _build_text_bytes(self, *, text: str, qr_code: str = '') -> bytes:
        encoding = self._encoding_from_settings(self.settings)
        feed_lines_before_cut = int(self.settings.get('feed_lines_before_cut') or 5)
        normalized_text = str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n')
        if not normalized_text:
            raise ValueError('Receipt text is required.')
        normalized_text = '\n'.join(
            self._normalize_text_for_encoding(line, encoding=encoding) for line in normalized_text.split('\n')
        )

        esc = bytes([0x1B])
        gs = bytes([0x1D])
        content = b''.join(
            [
                esc + b'@',
                self._escpos_code_page_command(encoding, self.settings.get('code_page')),
                (normalized_text + ('\n' * max(feed_lines_before_cut, 0))).encode(encoding, errors='replace'),
            ]
        )
        qr_code = str(qr_code or '').strip()
        if qr_code:
            content += self._escpos_qr_code(qr_code)
        if self.settings.get('cut_after_print', True):
            content += gs + b'V' + bytes([0])
        return content

    def _write_raw(self, printer_name: str, payload: bytes) -> None:
        if os.name != 'nt':
            raise RuntimeError('Windows raw printing is only available on Windows hosts.')

        winspool = ctypes.WinDLL('winspool.drv', use_last_error=True)
        open_printer = winspool.OpenPrinterW
        open_printer.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
        open_printer.restype = wintypes.BOOL

        close_printer = winspool.ClosePrinter
        close_printer.argtypes = [wintypes.HANDLE]
        close_printer.restype = wintypes.BOOL

        start_doc = winspool.StartDocPrinterW
        start_doc.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOCINFO)]
        start_doc.restype = wintypes.DWORD

        end_doc = winspool.EndDocPrinter
        end_doc.argtypes = [wintypes.HANDLE]
        end_doc.restype = wintypes.BOOL

        start_page = winspool.StartPagePrinter
        start_page.argtypes = [wintypes.HANDLE]
        start_page.restype = wintypes.BOOL

        end_page = winspool.EndPagePrinter
        end_page.argtypes = [wintypes.HANDLE]
        end_page.restype = wintypes.BOOL

        write_printer = winspool.WritePrinter
        write_printer.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        write_printer.restype = wintypes.BOOL

        printer_handle = wintypes.HANDLE()
        if not open_printer(printer_name, ctypes.byref(printer_handle), None):
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            document = DOCINFO('Chek', None, 'RAW')
            if not start_doc(printer_handle, 1, ctypes.byref(document)):
                raise ctypes.WinError(ctypes.get_last_error())

            try:
                if not start_page(printer_handle):
                    raise ctypes.WinError(ctypes.get_last_error())

                written = wintypes.DWORD(0)
                buffer = ctypes.create_string_buffer(payload)
                if not write_printer(printer_handle, buffer, len(payload), ctypes.byref(written)):
                    raise ctypes.WinError(ctypes.get_last_error())

                if written.value != len(payload):
                    raise RuntimeError('Incomplete printer write.')

                if not end_page(printer_handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                if not end_doc(printer_handle):
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close_printer(printer_handle)

    def _write_socket(self, host: str, port: int, payload: bytes) -> None:
        if not host:
            raise ValueError('LAN printer host is not configured.')
        if port <= 0:
            raise ValueError('LAN printer port is not configured.')

        with socket.create_connection((host, port), timeout=8) as connection:
            connection.settimeout(8)
            connection.sendall(payload)

    def print_prebill(self, order, payload):
        connection_type = (self.settings.get('connection_type') or self.settings.get('connectionType') or 'system_printer').strip()
        raw_payload = self._build_bytes(payload)
        return self._print_raw_payload(
            restaurant=order.restaurant,
            raw_payload=raw_payload,
            job_name=f'Cafe Postcode {self._order_label(payload)}',
            order_id=str(order.id),
            order_number=order.order_number,
        )

    def print_text(self, *, restaurant, text: str, qr_code: str = '', job_name: str = 'Cafe Postcode Receipt'):
        raw_payload = self._build_text_bytes(text=text, qr_code=qr_code)
        return self._print_raw_payload(
            restaurant=restaurant,
            raw_payload=raw_payload,
            job_name=job_name,
        )

    def _print_raw_payload(self, *, restaurant, raw_payload: bytes, job_name: str, order_id: str = '', order_number=None):
        connection_type = (self.settings.get('connection_type') or self.settings.get('connectionType') or 'system_printer').strip()
        printer_name = (self.settings.get('printer_name') or '').strip()
        host = (self.settings.get('host') or '').strip()
        port = int(self.settings.get('port') or 9100)

        if self._use_local_agent():
            try:
                LocalAgentCommandService().printer_raw(
                    restaurant=restaurant,
                    payload={
                        'connectionType': connection_type,
                        'printerName': printer_name,
                        'host': host,
                        'port': port,
                        'payloadBase64': base64.b64encode(raw_payload).decode('ascii'),
                        'jobName': job_name,
                    },
                    timeout_seconds=15,
                )
            except LocalAgentUnavailableError as error:
                raise RuntimeError(str(error)) from error
            except LocalAgentCommandError as error:
                raise RuntimeError(str(error)) from error
        elif connection_type == 'socket':
            self._write_socket(host, port, raw_payload)
        else:
            if not printer_name:
                raise ValueError('Printer name is not configured for the live printer integration.')
            self._write_raw(printer_name, raw_payload)

        return {
            'ok': True,
            'provider': self.config.provider,
            'connection_type': connection_type,
            'printer_name': printer_name,
            'host': host,
            'port': port if connection_type == 'socket' else None,
            'printed_at': timezone.now().isoformat(),
            'order_id': order_id,
            'order_number': order_number,
        }

    def _use_local_agent(self) -> bool:
        transport = str(self.settings.get('transport') or self.settings.get('transportType') or '').strip()
        if transport:
            return transport == 'local-agent'
        if 'use_local_agent' in self.settings:
            return bool(self.settings.get('use_local_agent'))
        if 'useLocalAgent' in self.settings:
            return bool(self.settings.get('useLocalAgent'))
        return True
