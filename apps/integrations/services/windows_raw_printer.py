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

    def _build_lines(self, payload: dict) -> list[str]:
        encoding = self.settings.get('encoding', 'cp1251')
        paper_width_mm = int(self.settings.get('paper_width_mm') or 80)
        width = self._chars_per_line(paper_width_mm)
        separator = '-' * width
        lines = [
            self._safe_text(payload['restaurant_name'], encoding=encoding),
            'PRECHEK',
            separator,
            self._safe_text(f"Buyurtma: A{int(payload['order_number']):05d}", encoding=encoding),
            self._safe_text(payload['channel_label'], encoding=encoding),
        ]

        table_label = payload.get('table_label')
        if table_label:
            lines.append(self._safe_text(table_label, encoding=encoding))

        waiter_name = payload.get('waiter_name')
        if waiter_name:
            lines.append(self._safe_text(f'Ofitsiant: {waiter_name}', encoding=encoding))

        lines.extend(
            [
                self._safe_text(f"Vaqt: {payload['printed_at_label']}", encoding=encoding),
                separator,
            ]
        )

        for item in payload.get('items', []):
            item_name = self._safe_text(item.get('name', ''), encoding=encoding)
            quantity = int(item.get('quantity') or 0)
            line_total = self._format_money(item.get('line_total'))
            lines.append(self._pad_line(f'{item_name} x{quantity}', line_total, width=width))
            item_note = self._safe_text(item.get('note') or '', encoding=encoding)
            if item_note:
                lines.append(f'  {item_note[: max(width - 2, 0)]}')

        lines.extend(
            [
                separator,
                self._pad_line('Mahsulotlar narxi', self._format_money(payload.get('subtotal')), width=width),
                self._pad_line('Xizmat narxi', self._format_money(payload.get('service_fee')), width=width),
                self._pad_line('Jami', self._format_money(payload.get('total')), width=width),
            ]
        )

        order_note = self._safe_text(payload.get('order_note') or '', encoding=encoding)
        if order_note:
            lines.extend([separator, f'Izoh: {order_note[: max(width - 6, 0)]}'])

        lines.append('')
        return lines

    def _build_bytes(self, payload: dict) -> bytes:
        encoding = self.settings.get('encoding', 'cp1251')
        feed_lines_before_cut = int(self.settings.get('feed_lines_before_cut') or 6)
        body = '\n'.join(self._build_lines(payload))
        esc = bytes([0x1B])
        gs = bytes([0x1D])
        content = b''.join(
            [
                esc + b'@',
                self._escpos_code_page_command(encoding, self.settings.get('code_page')),
                body.encode(encoding, errors='replace'),
            ]
        )
        if feed_lines_before_cut > 0:
            content += esc + b'd' + bytes([min(feed_lines_before_cut, 10)])
        if self.settings.get('cut_after_print', True):
            content += gs + b'V' + bytes([0])
        return content

    def _build_text_bytes(self, *, text: str) -> bytes:
        encoding = self.settings.get('encoding', 'cp1251')
        feed_lines_before_cut = int(self.settings.get('feed_lines_before_cut') or 5)
        normalized_text = str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized_text:
            raise ValueError('Receipt text is required.')

        esc = bytes([0x1B])
        gs = bytes([0x1D])
        content = b''.join(
            [
                esc + b'@',
                self._escpos_code_page_command(encoding, self.settings.get('code_page')),
                (normalized_text + ('\n' * max(feed_lines_before_cut, 0))).encode(encoding, errors='replace'),
            ]
        )
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
            job_name=f'Cafe Postcode A{int(order.order_number):05d}',
            order_id=str(order.id),
            order_number=order.order_number,
        )

    def print_text(self, *, restaurant, text: str, job_name: str = 'Cafe Postcode Receipt'):
        raw_payload = self._build_text_bytes(text=text)
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
