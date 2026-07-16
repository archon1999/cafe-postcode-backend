def build_legacy_receipt_payload(*, snapshot: dict, fiscal_result: dict | None = None) -> dict:
    restaurant = snapshot['restaurant']
    order = snapshot['order']
    payment = snapshot['payment']
    totals = snapshot['totals']
    payload = dict(fiscal_result or {})
    payload.update(
        {
            'restaurant_name': restaurant['name'],
            'restaurant_legal_name': restaurant['legalName'],
            'restaurant_address': restaurant['address'],
            'restaurant_phone': restaurant['phone'],
            'restaurant_social': restaurant['social'],
            'tax_number': restaurant['taxNumber'],
            'order_id': order['id'],
            'order_number': order['displayNumber'],
            'order_label': f"#{order['displayNumber']}",
            'channel': order['channel'],
            'channel_label': order['channelLabel'],
            'table_label': f"Stol: {order['table']}" if order['table'] else '',
            'waiter_name': order['waiter'],
            'cashier_name': order['cashier'],
            'order_note': order['note'],
            'items': [
                {
                    'name': item['name'],
                    'quantity': item['quantity'],
                    'unit_price': item['unitPrice'],
                    'line_total': item['lineTotal'],
                    'note': item['note'],
                }
                for item in snapshot['items']
            ],
            'subtotal': totals['subtotal'],
            'service_fee': totals['serviceFee'],
            'vat_amount': totals['vat'],
            'total': totals['total'],
            'payment_method': payment['method'],
            'amount': payment['amount'],
            'cash_amount': payment['cash'],
            'card_amount': payment['card'],
            'change': payment['change'],
            'paid_at': payment['paidAt'],
        }
    )
    return payload
