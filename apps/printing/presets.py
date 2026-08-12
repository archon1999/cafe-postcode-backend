from copy import deepcopy


KITCHEN_TICKET = 'kitchen_ticket'
PAYMENT_RECEIPT_PLAIN = 'payment_receipt_plain'
PAYMENT_RECEIPT_FISCAL = 'payment_receipt_fiscal'
PRINT_KINDS = (KITCHEN_TICKET, PAYMENT_RECEIPT_PLAIN, PAYMENT_RECEIPT_FISCAL)


def get_shift_report_layout() -> dict:
    """Internal fixed layout for POS and Fiscal Drive shift summaries."""
    return {
        'schemaVersion': 1,
        'paperWidthMm': 80,
        'blocks': [
            {'id': 'title', 'type': 'text', 'text': 'Hisobot', 'align': 'center', 'bold': True, 'size': 'large'},
            {'id': 'header-divider', 'type': 'divider'},
            {
                'id': 'identity',
                'type': 'metadata',
                'rows': [
                    {'label': 'STIR', 'value': '{{restaurant.taxNumber}}'},
                    {'label': 'Terminal', 'value': '{{report.terminalId}}'},
                    {'label': 'Kassa', 'value': '{{shift.cashDeskName}}'},
                    {'label': 'Kassir', 'value': '{{shift.cashierName}}'},
                    {'label': 'Sana', 'value': '{{report.printedAt}}'},
                ],
            },
            {'id': 'period-divider', 'type': 'divider'},
            {'id': 'report-kind', 'type': 'text', 'text': '{{report.label}}', 'align': 'center', 'bold': True},
            {
                'id': 'period',
                'type': 'metadata',
                'rows': [
                    {'label': 'Ochilish', 'value': '{{report.openedAt}}'},
                    {'label': 'Yopilish', 'value': '{{report.closedAt}}'},
                    {'label': 'Birinchi chek', 'value': '{{report.firstReceipt}}'},
                    {'label': 'Oxirgi chek', 'value': '{{report.lastReceipt}}'},
                ],
            },
            {'id': 'sales-title', 'type': 'text', 'text': 'Sotuv', 'align': 'center', 'bold': True},
            {
                'id': 'sales',
                'type': 'totals',
                'rows': [
                    {'label': 'Sotuvlar', 'value': '{{report.saleCount}}'},
                    {'label': 'Naqd — prechek', 'value': '{{report.cashPrecheckSale}}', 'format': 'money'},
                    {'label': 'Naqd — chek', 'value': '{{report.cashReceiptSale}}', 'format': 'money'},
                    {'label': 'Karta — prechek', 'value': '{{report.cardPrecheckSale}}', 'format': 'money'},
                    {'label': 'Karta — chek', 'value': '{{report.cardReceiptSale}}', 'format': 'money'},
                    {'label': 'QR', 'value': '{{report.qrSale}}', 'format': 'money', 'hideZero': True},
                    {'label': 'QQS', 'value': '{{report.vatSale}}', 'format': 'money', 'hideZero': True},
                    {'label': 'Jami', 'value': '{{report.totalSale}}', 'format': 'money', 'bold': True},
                ],
            },
            {'id': 'refund-title', 'type': 'text', 'text': 'Qaytarish', 'align': 'center', 'bold': True},
            {
                'id': 'refunds',
                'type': 'totals',
                'rows': [
                    {'label': 'Qaytarishlar', 'value': '{{report.refundCount}}'},
                    {'label': 'Naqd', 'value': '{{report.cashRefund}}', 'format': 'money'},
                    {'label': 'Karta', 'value': '{{report.cardRefund}}', 'format': 'money'},
                    {'label': 'QR', 'value': '{{report.qrRefund}}', 'format': 'money', 'hideZero': True},
                    {'label': 'QQS', 'value': '{{report.vatRefund}}', 'format': 'money', 'hideZero': True},
                    {'label': 'Jami', 'value': '{{report.totalRefund}}', 'format': 'money', 'bold': True},
                ],
            },
            {
                'id': 'expenses',
                'type': 'totals',
                'rows': [
                    {'label': 'Xarajatlar', 'value': '{{report.expenseTotal}}', 'format': 'money', 'bold': True},
                    {'label': 'Kassada qolgan', 'value': '{{report.netCashAfterExpenses}}', 'format': 'money', 'bold': True},
                ],
            },
            {'id': 'footer-divider', 'type': 'divider'},
            {
                'id': 'device',
                'type': 'metadata',
                'rows': [
                    {'label': 'FM', 'value': '{{report.factoryId}}'},
                    {'label': 'SN', 'value': '{{report.serialNumber}}'},
                ],
            },
            {'id': 'feed', 'type': 'feed', 'lines': 5},
            {'id': 'cut', 'type': 'cut'},
        ],
    }

COMMON_VARIABLES = (
    'restaurant.name',
    'restaurant.legalName',
    'restaurant.address',
    'restaurant.phone',
    'restaurant.social',
    'restaurant.taxNumber',
    'order.displayNumber',
    'order.channel',
    'order.channelLabel',
    'order.table',
    'order.hall',
    'order.guestCount',
    'order.openedAt',
    'order.waiter',
    'order.cashier',
    'order.note',
    'order.deliveryPhone',
    'order.deliveryAddress',
    'item.name',
    'item.quantity',
    'item.unitPrice',
    'item.lineTotal',
    'item.vat',
    'item.vatPercent',
    'item.note',
    'system.copyNumber',
    'system.isReprint',
)

KITCHEN_VARIABLES = COMMON_VARIABLES + (
    'kitchen.ticketNumber',
    'kitchen.prepStation',
    'kitchen.createdAt',
    'totals.total',
)

PAYMENT_VARIABLES = COMMON_VARIABLES + (
    'payment.method',
    'payment.amount',
    'payment.cash',
    'payment.card',
    'payment.change',
    'payment.paidAt',
    'payment.operationType',
    'totals.subtotal',
    'totals.serviceFee',
    'totals.vat',
    'totals.vatPercent',
    'totals.serviceFeePercent',
    'totals.total',
)

FISCAL_VARIABLES = PAYMENT_VARIABLES + (
    'fiscal.receiptNumber',
    'fiscal.terminalId',
    'fiscal.factoryId',
    'fiscal.fiscalSign',
    'fiscal.qrUrl',
    'fiscal.registeredAt',
)

VARIABLES_BY_KIND = {
    KITCHEN_TICKET: KITCHEN_VARIABLES,
    PAYMENT_RECEIPT_PLAIN: PAYMENT_VARIABLES,
    PAYMENT_RECEIPT_FISCAL: FISCAL_VARIABLES,
}

VARIABLE_GROUPS = (
    {'key': 'restaurant', 'label': 'Restoran'},
    {'key': 'order', 'label': 'Buyurtma'},
    {'key': 'item', 'label': 'Pozitsiya'},
    {'key': 'kitchen', 'label': 'Oshxona'},
    {'key': 'payment', 'label': "To'lov"},
    {'key': 'totals', 'label': 'Jami'},
    {'key': 'fiscal', 'label': 'Fiskal'},
    {'key': 'system', 'label': 'Tizim'},
)

SAMPLE_DATA = {
    'restaurant': {
        'name': 'Cafe Postcode',
        'legalName': 'CAFE POSTCODE MCHJ',
        'address': 'Toshkent shahri, Amir Temur ko‘chasi 10',
        'phone': '+998 90 123 45 67',
        'social': '@cafepostcode',
        'taxNumber': '309123456',
    },
    'order': {
        'displayNumber': '1042',
        'channel': 'hall',
        'channelLabel': 'Zal',
        'table': '12-stol',
        'hall': 'Asosiy zal',
        'guestCount': 3,
        'openedAt': '10.07.2026 15:42',
        'waiter': 'Aziza Karimova',
        'cashier': 'Nodira Aliyeva',
        'note': 'Achchiq sous alohida',
        'deliveryPhone': '90-123-45-67',
        'deliveryAddress': 'Chilonzor 12',
    },
    'items': [
        {
            'name': 'Osh',
            'quantity': 2,
            'unitPrice': 30000,
            'lineTotal': 60000,
            'vat': 6429,
            'vatPercent': 12,
            'note': '',
        },
        {
            'name': 'Achchiq-chuchuk salat',
            'quantity': 1,
            'unitPrice': 15000,
            'lineTotal': 15000,
            'vat': 1607,
            'vatPercent': 12,
            'note': 'Piyozsiz',
        },
    ],
    'kitchen': {'ticketNumber': 'K-1042', 'prepStation': 'Issiq oshxona', 'createdAt': '10.07.2026 15:43'},
    'payment': {
        'method': 'Naqd',
        'amount': 82500,
        'cash': 100000,
        'card': 0,
        'change': 17500,
        'paidAt': '10.07.2026 16:18',
        'operationType': 'sale',
    },
    'totals': {
        'subtotal': 75000,
        'serviceFee': 7500,
        'serviceFeePercent': 10,
        'vat': 8839,
        'vatPercent': 12,
        'total': 82500,
    },
    'fiscal': {
        'receiptNumber': '000001042',
        'terminalId': 'UZ123456789',
        'factoryId': 'FR00001234',
        'fiscalSign': '123456789012',
        'qrUrl': 'https://ofd.uz/receipt/example',
        'registeredAt': '10.07.2026 16:18',
    },
    'system': {'copyNumber': 1, 'isReprint': False},
}


def _header_blocks(*, detailed: bool) -> list[dict]:
    blocks = [
        {
            'id': 'restaurant-name',
            'type': 'text',
            'role': 'restaurant_header',
            'text': '{{restaurant.name}}',
            'align': 'center',
            'bold': True,
            'size': 'large',
        },
    ]
    if detailed:
        blocks.extend(
            [
                {'id': 'restaurant-address', 'type': 'text', 'text': '{{restaurant.address}}', 'align': 'center'},
                {'id': 'restaurant-phone', 'type': 'text', 'text': '{{restaurant.phone}}', 'align': 'center'},
            ]
        )
    return blocks


def _order_blocks(*, kitchen: bool, detailed: bool) -> list[dict]:
    rows = [
        {'label': 'Buyurtma', 'value': '{{order.displayNumber}}'},
        {'label': 'Turi', 'value': '{{order.channelLabel}}'},
        {'label': 'Stol', 'value': '{{order.table}}'},
    ]
    if detailed:
        rows.extend(
            [
                {'label': 'Zal', 'value': '{{order.hall}}'},
                {'label': 'Mehmon', 'value': '{{order.guestCount}}'},
                {'label': 'Ofitsiant', 'value': '{{order.waiter}}'},
            ]
        )
    if kitchen:
        rows.insert(1, {'label': 'Stansiya', 'value': '{{kitchen.prepStation}}'})
        rows.append({'label': 'Vaqt', 'value': '{{kitchen.createdAt}}'})
    return [
        {'id': 'order-divider', 'type': 'divider'},
        {'id': 'order-meta', 'type': 'metadata', 'role': 'order_header', 'rows': rows},
        {'id': 'items-divider', 'type': 'divider'},
    ]


def _items_block(*, show_price: bool, large: bool = False, show_vat: bool = False) -> dict:
    columns = [{'label': 'Nomi', 'value': '{{item.name}}', 'grow': 1}]
    columns.append({'label': 'Soni', 'value': 'x{{item.quantity}}', 'align': 'right'})
    if show_price:
        columns.append({'label': 'Summa', 'value': '{{item.lineTotal}}', 'align': 'right', 'format': 'money'})
    block = {
        'id': 'items',
        'type': 'items_table',
        'role': 'items',
        'columns': columns,
        'showNotes': True,
        'size': 'large' if large else 'normal',
    }
    if show_vat:
        block.update(
            {
                'showVat': True,
                'vatLabel': 'QQS ({{item.vatPercent}}%)',
                'vatValue': '{{item.vat}}',
            }
        )
    return block


def _payment_blocks(*, fiscal: bool, detailed: bool) -> list[dict]:
    total_rows = [
        {'label': 'Oraliq jami', 'value': '{{totals.subtotal}}', 'format': 'money'},
        {'label': 'Xizmat haqi', 'value': '{{totals.serviceFee}}', 'format': 'money'},
        {'label': 'JAMI', 'value': '{{totals.total}}', 'format': 'money', 'bold': True},
    ]
    if fiscal:
        total_rows.insert(
            -1,
            {
                'label': 'Sh.j. QQS ({{totals.vatPercent}}%)',
                'value': '{{totals.vat}}',
                'format': 'money',
                'hideZero': True,
            },
        )
    blocks = [
        {'id': 'totals-divider', 'type': 'divider'},
        {'id': 'totals', 'type': 'totals', 'role': 'totals', 'rows': total_rows},
        {
            'id': 'payment',
            'type': 'metadata',
            'role': 'payment',
            'rows': [
                {'label': "To'lov", 'value': '{{payment.method}}'},
                {'label': "To'landi", 'value': '{{payment.amount}}', 'format': 'money'},
                {'label': 'Qaytim', 'value': '{{payment.change}}', 'format': 'money'},
                {'label': 'Vaqt', 'value': '{{payment.paidAt}}'},
            ],
        },
    ]
    if fiscal:
        blocks.extend(
            [
                {'id': 'fiscal-divider', 'type': 'divider'},
                {
                    'id': 'fiscal-meta',
                    'type': 'metadata',
                    'role': 'fiscal',
                    'locked': True,
                    'rows': [
                        {'label': 'Fiskal chek', 'value': '{{fiscal.receiptNumber}}'},
                        {'label': 'Terminal', 'value': '{{fiscal.terminalId}}'},
                        {'label': 'Fiskal belgi', 'value': '{{fiscal.fiscalSign}}'},
                    ],
                },
                {
                    'id': 'fiscal-qr',
                    'type': 'qr',
                    'role': 'fiscal_qr',
                    'locked': True,
                    'value': '{{fiscal.qrUrl}}',
                    'align': 'center',
                    'qrScale': 2,
                },
            ]
        )
    return blocks


def build_layout(*, kind: str, detailed: bool, kitchen_large: bool = False) -> dict:
    if kind not in PRINT_KINDS:
        raise KeyError(kind)

    is_kitchen = kind == KITCHEN_TICKET
    is_fiscal = kind == PAYMENT_RECEIPT_FISCAL
    blocks = _header_blocks(detailed=detailed)
    blocks.extend(_order_blocks(kitchen=is_kitchen, detailed=detailed))
    blocks.append(_items_block(show_price=not is_kitchen, large=kitchen_large, show_vat=is_fiscal))
    if is_kitchen:
        blocks.extend(
            [
                {'id': 'order-note-divider', 'type': 'divider'},
                {'id': 'order-note', 'type': 'text', 'text': '{{order.note}}', 'bold': True},
            ]
        )
    else:
        blocks.extend(_payment_blocks(fiscal=is_fiscal, detailed=detailed))
    blocks.extend(
        [
            {'id': 'footer-divider', 'type': 'divider'},
            {'id': 'footer', 'type': 'text', 'text': 'Xaridingiz uchun rahmat!', 'align': 'center'},
            {'id': 'feed', 'type': 'feed', 'lines': 2},
            {'id': 'cut', 'type': 'cut'},
        ]
    )
    return {'schemaVersion': 1, 'paperWidthMm': 80, 'blocks': blocks}


def build_legacy_layout(kind: str) -> dict:
    """Canonical 80 mm layout matching the receipt used before the template editor."""
    if kind not in PRINT_KINDS:
        raise KeyError(kind)

    is_kitchen = kind == KITCHEN_TICKET
    is_fiscal = kind == PAYMENT_RECEIPT_FISCAL
    blocks = [
        {
            'id': 'restaurant-name',
            'type': 'text',
            'role': 'restaurant_header',
            'text': '{{restaurant.name}}',
            'align': 'center',
            'bold': True,
            'size': 'large',
        },
        {'id': 'header-divider', 'type': 'divider'},
        {
            'id': 'order-number',
            'type': 'text',
            'role': 'order_header',
            'text': 'Buyurtma raqami: {{order.displayNumber}}',
            'align': 'center',
            'bold': True,
            'size': 'large',
        },
        {'id': 'restaurant-divider', 'type': 'divider'},
        {
            'id': 'restaurant-details',
            'type': 'metadata',
            'rows': [
                {'label': 'Manzil', 'value': '{{restaurant.address}}'},
                {'label': 'Tel', 'value': '{{restaurant.phone}}'},
                {'label': 'Ijtimoiy tarmoq', 'value': '{{restaurant.social}}'},
            ],
        },
        {'id': 'order-details-divider', 'type': 'divider'},
        {
            'id': 'order-details',
            'type': 'metadata',
            'rows': [
                {'label': 'Buyurtma vaqti', 'value': '{{order.openedAt}}'},
                {'label': 'Buyurtma turi', 'value': '{{order.channelLabel}}'},
                {'label': 'Stol', 'value': '{{order.table}}'},
                {'label': 'Zal', 'value': '{{order.hall}}'},
                {'label': 'Ofitsiant', 'value': '{{order.waiter}}'},
                {'label': 'Kassir', 'value': '{{order.cashier}}'},
                {'label': 'Mijoz tel', 'value': '{{order.deliveryPhone}}'},
                {'label': 'Mijoz manzil', 'value': '{{order.deliveryAddress}}'},
                {'label': 'Stansiya', 'value': '{{kitchen.prepStation}}'} if is_kitchen else None,
            ],
        },
        {'id': 'items-divider', 'type': 'divider'},
        {
            'id': 'items',
            'type': 'items_table',
            'role': 'items',
            'columns': [
                {'label': 'Mahsulot', 'value': '{{item.name}}', 'grow': 1},
                {'label': 'Soni', 'value': 'x{{item.quantity}}', 'align': 'right'},
                {'label': 'Summa', 'value': '{{item.lineTotal}}', 'align': 'right', 'format': 'money'},
            ],
            'showNotes': True,
            'separatorAfterEach': True,
            **(
                {
                    'showVat': True,
                    'vatLabel': 'QQS ({{item.vatPercent}}%)',
                    'vatValue': '{{item.vat}}',
                }
                if is_fiscal
                else {}
            ),
        },
    ]
    order_details = next(block for block in blocks if block['id'] == 'order-details')
    order_details['rows'] = [row for row in order_details['rows'] if row is not None]

    if is_kitchen:
        blocks.extend(
            [
                {
                    'id': 'kitchen-total',
                    'type': 'totals',
                    'rows': [{'label': 'Jami', 'value': '{{totals.total}}', 'format': 'money'}],
                },
                {'id': 'order-note', 'type': 'metadata', 'rows': [{'label': 'Izoh', 'value': '{{order.note}}'}]},
            ]
        )
    else:
        blocks.extend(
            [
                {'id': 'total-top-divider', 'type': 'divider', 'character': '='},
                {
                    'id': 'totals',
                    'type': 'totals',
                    'role': 'totals',
                    'rows': [
                        {'label': 'JAMI', 'value': '{{totals.total}}', 'format': 'money', 'bold': True},
                        *(
                            [
                                {
                                    'label': 'Sh.j. QQS ({{totals.vatPercent}}%)',
                                    'value': '{{totals.vat}}',
                                    'format': 'money',
                                    'hideZero': True,
                                }
                            ]
                            if is_fiscal
                            else []
                        ),
                        {'label': 'XIZMAT HAQI', 'value': '{{totals.serviceFee}}', 'format': 'money', 'hideZero': True},
                    ],
                },
                {'id': 'total-bottom-divider', 'type': 'divider', 'character': '='},
                {
                    'id': 'payment',
                    'type': 'metadata',
                    'role': 'payment',
                    'rows': [
                        {'label': "To'lov", 'value': '{{payment.method}}'},
                        {'label': 'NAQD PUL', 'value': '{{payment.cash}}', 'format': 'money', 'hideZero': True},
                        {'label': 'BANK KARTASI', 'value': '{{payment.card}}', 'format': 'money', 'hideZero': True},
                        {'label': 'Qaytim', 'value': '{{payment.change}}', 'format': 'money', 'hideZero': True},
                    ],
                },
            ]
        )
    if is_fiscal:
        blocks.extend(
            [
                {'id': 'fiscal-divider', 'type': 'divider'},
                {
                    'id': 'fiscal-meta',
                    'type': 'metadata',
                    'role': 'fiscal',
                    'locked': True,
                    'rows': [
                        {'label': 'STIR', 'value': '{{restaurant.taxNumber}}'},
                        {'label': 'FM', 'value': '{{fiscal.factoryId}}'},
                        {'label': 'FB', 'value': '{{fiscal.fiscalSign}}'},
                        {'label': 'NKM S/R', 'value': '{{fiscal.terminalId}}'},
                        {'label': 'Fiskal chek', 'value': '{{fiscal.receiptNumber}}'},
                    ],
                },
                {
                    'id': 'fiscal-qr',
                    'type': 'qr',
                    'role': 'fiscal_qr',
                    'locked': True,
                    'value': '{{fiscal.qrUrl}}',
                    'align': 'center',
                    'qrScale': 2,
                },
            ]
        )
    if not is_kitchen:
        blocks.append({'id': 'order-note', 'type': 'metadata', 'rows': [{'label': 'Izoh', 'value': '{{order.note}}'}]})
    blocks.extend(
        [
            {'id': 'footer-divider', 'type': 'divider'},
            {
                'id': 'footer-thanks',
                'type': 'text',
                'text': 'Buyurtmangiz uchun rahmat!',
                'align': 'center',
            },
            {'id': 'footer-appetite', 'type': 'text', 'text': 'Yoqimli ishtaha!', 'align': 'center'},
            {'id': 'feed', 'type': 'feed', 'lines': 2},
            {'id': 'cut', 'type': 'cut'},
        ]
    )
    return {'schemaVersion': 1, 'paperWidthMm': 80, 'blocks': blocks}


PRESET_PACKS = (
    {'key': 'legacy_80', 'name': 'Classic', 'paperWidthMm': 80, 'detailed': False, 'kitchenLarge': False},
    {'key': 'standard_80', 'name': 'Compact', 'paperWidthMm': 80, 'detailed': False, 'kitchenLarge': False},
    {'key': 'detailed_80', 'name': 'Detailed', 'paperWidthMm': 80, 'detailed': True, 'kitchenLarge': False},
    {'key': 'kitchen_large_80', 'name': 'Large kitchen', 'paperWidthMm': 80, 'detailed': True, 'kitchenLarge': True},
)


def get_preset_layout(pack_key: str, kind: str) -> dict:
    pack = next((item for item in PRESET_PACKS if item['key'] == pack_key), None)
    if pack is None:
        raise KeyError(pack_key)
    if pack_key == 'legacy_80':
        return build_legacy_layout(kind)
    return build_layout(
        kind=kind,
        detailed=pack['detailed'],
        kitchen_large=bool(pack['kitchenLarge'] and kind == KITCHEN_TICKET),
    )


def get_preset_catalog() -> list[dict]:
    return [
        {
            'key': pack['key'],
            'name': pack['name'],
            'paperWidthMm': pack['paperWidthMm'],
            'templates': {kind: get_preset_layout(pack['key'], kind) for kind in PRINT_KINDS},
        }
        for pack in PRESET_PACKS
    ]


def get_sample_data() -> dict:
    return deepcopy(SAMPLE_DATA)
