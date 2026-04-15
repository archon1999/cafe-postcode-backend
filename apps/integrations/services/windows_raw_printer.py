import ctypes
import os
from ctypes import wintypes

from django.utils import timezone


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
        return text.encode(encoding, errors='replace').decode(encoding, errors='replace')

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
        encoding = self.settings.get('encoding', 'cp437')
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

        lines.extend(['', '', ''])
        return lines

    def _build_bytes(self, payload: dict) -> bytes:
        encoding = self.settings.get('encoding', 'cp437')
        body = '\n'.join(self._build_lines(payload))
        esc = bytes([0x1B])
        gs = bytes([0x1D])
        content = b''.join([esc + b'@', body.encode(encoding, errors='replace')])
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

    def print_prebill(self, order, payload):
        printer_name = (self.settings.get('printer_name') or '').strip()
        if not printer_name:
            raise ValueError('Printer name is not configured for the live printer integration.')

        raw_payload = self._build_bytes(payload)
        self._write_raw(printer_name, raw_payload)
        return {
            'ok': True,
            'provider': self.config.provider,
            'mode': self.config.mode,
            'printer_name': printer_name,
            'printed_at': timezone.now().isoformat(),
            'order_id': str(order.id),
            'order_number': order.order_number,
        }
