import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model, get_receipt_model
from apps.billing.services.cash_shift import CashShiftService
from apps.catalog.utils.cash_sale import is_catalog_item_cash_sale_forbidden
from apps.integrations.services import build_order_label, charge_payment, issue_fiscal_receipts
from apps.integrations.services.marta_softpos import DEFAULT_AMOUNT_MULTIPLIER, DEFAULT_TIMEOUT_SECONDS, JAVA_LONG_MAX
from apps.printing.services import attach_receipt_print_document
from apps.sales.helpers import get_order_model
from apps.sales.services import OrderStateService, OrderSubmissionService, validate_order_markings
from common.api.permissions import POS_FISCAL_RECEIPTS_SKIP_PERMISSION, has_permission_code

logger = logging.getLogger(__name__)

Order = get_order_model()
Payment = get_payment_model()
Receipt = get_receipt_model()


class OrderPaymentService:
    order_submission_service_class = OrderSubmissionService
    state_service_class = OrderStateService
    shift_service_class = CashShiftService

    def initiate_marta_card_payment(self, *, order: Order, amount, register_fiscal=True, received_by, cash_shift=None):
        from apps.billing.serializers import PaymentSerializer

        state_service = self.state_service_class()
        state_service.ensure_order_can_be_paid(order=order)
        state_service.ensure_delivery_details(order=order)
        if self._should_submit_before_payment(order=order):
            self.order_submission_service_class().submit(order)

        self._validate_shift(order=order, cash_shift=cash_shift)
        if not register_fiscal and not has_permission_code(received_by, POS_FISCAL_RECEIPTS_SKIP_PERMISSION):
            raise ValidationError({'register_fiscal': _('You do not have permission to skip fiscal registration.')})
        validate_order_markings(order)
        serializer = PaymentSerializer(
            data={
                'method': Payment.Method.CARD,
                'amount': amount,
                'register_fiscal': register_fiscal,
            }
        )
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data['amount']

        cash_desk = cash_shift.cash_desk
        if Payment.Method.CARD not in set(cash_desk.enabled_payment_methods or []):
            raise ValidationError({'method': _('Selected payment method is disabled on the active cash desk.')})

        config = getattr(cash_desk, 'payment_integration', None)
        if (
            config is None
            or config.kind != 'payment'
            or config.provider != 'marta-softpos'
            or not config.is_enabled
        ):
            raise ValidationError({'detail': _('MARTA SoftPOS payment integration is not configured for the active cash desk.')})

        self._validate_payment_amount(order=order, amount=amount)
        settings = dict(config.settings or {})
        if str(settings.get('transport') or '').strip() == 'local-agent':
            raise ValidationError({
                'detail': _(
                    'MARTA browser-direct payment flow is disabled. Refresh POS and use the card payment flow through the local agent.'
                )
            })
        endpoint_url = str(settings.get('endpoint_url') or settings.get('endpointUrl') or '').rstrip('/')
        if not endpoint_url:
            raise ValidationError({'detail': _('MARTA SoftPOS endpoint URL is not configured.')})

        payment = serializer.save(order=order, received_by=received_by, cash_shift=cash_shift, cash_desk=cash_desk)

        amount_multiplier = self._positive_int(
            settings.get('amount_multiplier') or settings.get('amountMultiplier'),
            DEFAULT_AMOUNT_MULTIPLIER,
        )
        timeout_seconds = self._positive_int(
            settings.get('timeout_seconds') or settings.get('timeoutSeconds'),
            int(DEFAULT_TIMEOUT_SECONDS),
        )
        pid = self._marta_pid(payment=payment)
        tax_number = str(
            settings.get('tax_number')
            or settings.get('taxNumber')
            or getattr(order.restaurant, 'tax_number', '')
            or ''
        ).strip()
        marta_payload = {
            'endpoint_url': endpoint_url,
            'endpointUrl': endpoint_url,
            'pid': pid,
            'amount': int(payment.amount or 0) * amount_multiplier,
            'amount_multiplier': amount_multiplier,
            'amountMultiplier': amount_multiplier,
            'tax_number': tax_number,
            'taxNumber': tax_number,
            'timeout_seconds': timeout_seconds,
            'timeoutSeconds': timeout_seconds,
        }
        payment.provider_payload = {
            'ok': False,
            'provider': 'marta-softpos',
            'method': Payment.Method.CARD,
            'status': Payment.Status.PENDING,
            'reference': '',
            'pid': pid,
            'endpoint_url': endpoint_url,
            'amount_multiplier': amount_multiplier,
            'tax_number': tax_number,
            'timeout_seconds': timeout_seconds,
            'initiated_at': timezone.now().isoformat(),
        }
        payment.save(update_fields=['provider_payload', 'updated_at'])
        return {'payment': payment, 'marta': marta_payload}

    def complete_marta_terminal_payment(self, *, payment: Payment, terminal_result: dict, received_by):
        if payment.method != Payment.Method.CARD:
            raise ValidationError({'detail': _('Only card payments can be completed with MARTA terminal result.')})
        if payment.status != Payment.Status.PENDING:
            raise ValidationError({'detail': _('Only pending card payments can be completed with MARTA terminal result.')})

        status = str(terminal_result.get('status') or '').strip().upper()
        params = terminal_result.get('params') if isinstance(terminal_result.get('params'), dict) else {}
        if 'trx_id' in params and 'trxId' not in params:
            params = {**params, 'trxId': params['trx_id']}
        request_id = str(terminal_result.get('requestId') or terminal_result.get('request_id') or '')
        reference = str(params.get('trxId') or params.get('trx_id') or params.get('rrn') or request_id or '')
        message = str(terminal_result.get('message') or '').strip()
        ok = terminal_result.get('ok') is True and status == 'SUCCESS'
        previous_payload = dict(payment.provider_payload or {})
        debug = self._normalize_marta_debug_payload(terminal_result.get('debug') or {})
        provider_payload = {
            **previous_payload,
            'ok': ok,
            'provider': 'marta-softpos',
            'method': Payment.Method.CARD,
            'reference': reference,
            'requestId': request_id,
            'status': status or 'ERROR',
            'message': message,
            'params': params,
            'ac': terminal_result.get('ac') or params.get('ac'),
            'response': terminal_result.get('response') or terminal_result,
            'debug': debug,
            'browserError': terminal_result.get('browserError') or terminal_result.get('browser_error') or {},
            'processed_at': timezone.now().isoformat(),
        }

        payment.status = Payment.Status.SUCCEEDED if ok else Payment.Status.FAILED
        payment.external_ref = reference
        payment.provider_payload = provider_payload
        payment.paid_at = timezone.now() if ok else None
        payment.save(update_fields=['status', 'external_ref', 'provider_payload', 'paid_at', 'updated_at'])

        if not ok:
            detail = message or f'MARTA SoftPOS payment failed with status {status or "ERROR"}.'
            return {
                'payment': payment,
                'receipt': None,
                'receipts': [],
                'order': payment.order,
                'detail': detail,
            }

        paid_before_current = (
            payment.order.payments.filter(status=Payment.Status.SUCCEEDED)
            .exclude(pk=payment.pk)
            .aggregate(total=Sum('amount'))
            .get('total')
            or 0
        )
        remaining_amount = max(0, int(payment.order.total or 0) - int(paid_before_current or 0))
        if int(payment.amount or 0) > remaining_amount:
            payment.status = Payment.Status.FAILED
            payment.provider_payload = {
                **provider_payload,
                'ok': False,
                'status': 'ERROR',
                'message': 'Payment amount exceeds remaining total.',
            }
            payment.paid_at = None
            payment.save(update_fields=['status', 'provider_payload', 'paid_at', 'updated_at'])
            raise ValidationError({'amount': _('Payment amount cannot exceed the remaining total.')})

        return self._complete_successful_payment(order=payment.order, payment=payment, received_by=received_by)

    def process(self, *, order: Order, payload: dict, received_by, cash_shift=None, trusted_edge_replay=False):
        from apps.billing.serializers import PaymentSerializer

        edge_operation_id = str(payload.get('edge_operation_id') or payload.get('edgeOperationId') or '').strip()
        if edge_operation_id:
            existing = Payment.objects.filter(edge_operation_id=edge_operation_id).select_related('order').first()
            if existing is not None:
                if existing.order_id != order.id:
                    raise ValidationError({'edgeOperationId': _('Operation ID belongs to another order.')})
                receipts = list(existing.receipts.order_by('created_at'))
                return {
                    'payment': existing,
                    'receipt': receipts[0] if receipts else None,
                    'receipts': receipts,
                    'order': existing.order,
                    'detail': (existing.provider_payload or {}).get('detail', ''),
                }

        state_service = self.state_service_class()
        state_service.ensure_order_can_be_paid(order=order)
        state_service.ensure_delivery_details(order=order)
        if self._should_submit_before_payment(order=order):
            self.order_submission_service_class().submit(order)

        if cash_shift is None:
            raise ValidationError({'detail': _('Open a cashier shift before accepting payments.')})
        if cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': _('Only an open cashier shift can be used for payment.')})
        if cash_shift.cash_desk.restaurant_id != order.restaurant_id:
            raise ValidationError({'detail': _('Active cashier shift belongs to another restaurant.')})

        serializer = PaymentSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        manual_card_override = bool(serializer.validated_data.pop('manual_card_override', False))
        manual_card_reason = str(serializer.validated_data.pop('manual_card_reason', '') or '')
        edge_provider_result = serializer.validated_data.pop('edge_provider_result', None)
        if edge_provider_result is not None and not trusted_edge_replay:
            raise ValidationError({'edgeProviderResult': _('Only a trusted local agent may replay a terminal result.')})
        register_fiscal = bool(serializer.validated_data.get('register_fiscal', True))
        if not register_fiscal and not has_permission_code(received_by, POS_FISCAL_RECEIPTS_SKIP_PERMISSION):
            raise ValidationError({'register_fiscal': _('You do not have permission to skip fiscal registration.')})
        validate_order_markings(order)
        cash_desk = (
            cash_shift.cash_desk
            if cash_shift is not None
            else order.restaurant.cash_desks.filter(is_active=True).order_by('name').first()
        )
        if cash_desk and serializer.validated_data['method'] not in set(cash_desk.enabled_payment_methods or []):
            raise ValidationError({'method': _('Selected payment method is disabled on the active cash desk.')})
        if cash_desk and serializer.validated_data['method'] == Payment.Method.MIXED:
            enabled_methods = set(cash_desk.enabled_payment_methods or [])
            if not {Payment.Method.CASH, Payment.Method.CARD}.issubset(enabled_methods):
                raise ValidationError({'method': _('Mixed payment requires cash and card methods on the active cash desk.')})

        remaining_amount = self._remaining_amount(order=order)
        payment_amount = serializer.validated_data['amount']
        if remaining_amount <= 0:
            raise ValidationError({'amount': _('Order is already fully paid.')})
        if payment_amount > remaining_amount:
            raise ValidationError({'amount': _('Payment amount cannot exceed the remaining total.')})

        validated_edge_result = None
        if edge_provider_result is not None:
            validated_edge_result = self._validated_edge_provider_result(
                result=edge_provider_result,
                method=serializer.validated_data['method'],
                card_amount=serializer.validated_data['card_amount'],
                edge_operation_id=edge_operation_id,
            )
        payment = serializer.save(order=order, received_by=received_by, cash_shift=cash_shift, cash_desk=cash_desk)

        if validated_edge_result is not None:
            payment_result = validated_edge_result
        else:
            payment_result = charge_payment(
                order=order,
                payment=payment,
                manual_card_override=manual_card_override,
                manual_card_reason=manual_card_reason,
            )
        payment.status = Payment.Status.SUCCEEDED if payment_result.get('ok') else Payment.Status.FAILED
        payment.external_ref = payment_result.get('reference', '')
        payment.provider_payload = payment_result
        payment.paid_at = timezone.now() if payment.status == Payment.Status.SUCCEEDED else None
        payment.save(update_fields=['status', 'external_ref', 'provider_payload', 'paid_at', 'updated_at'])

        if payment.status == Payment.Status.FAILED:
            logger.warning(
                'Payment charge failed',
                extra={'order_id': str(order.pk), 'payment_id': str(payment.pk), 'method': payment.method},
            )
            return {
                'payment': payment,
                'receipt': None,
                'order': order,
                'detail': payment_result.get('detail') or payment_result.get('message') or _('Payment charge failed.'),
            }

        return self._complete_successful_payment(order=order, payment=payment, received_by=received_by)

    @staticmethod
    def _validated_edge_provider_result(*, result, method, card_amount, edge_operation_id):
        if not isinstance(result, dict):
            raise ValidationError({'edgeProviderResult': _('Terminal result must be an object.')})
        provider = str(result.get('provider') or '').strip()
        terminal_status = str(result.get('status') or '').strip().upper()
        reference = str(result.get('reference') or '').strip()
        result_operation_id = str(result.get('edgeOperationId') or result.get('edge_operation_id') or '').strip()
        try:
            charged_card_amount = int(result.get('cardAmount') or result.get('card_amount') or 0)
        except (TypeError, ValueError):
            charged_card_amount = 0

        errors = {}
        if method not in {Payment.Method.CARD, Payment.Method.MIXED}:
            errors['method'] = _('A terminal result is valid only for card or mixed payments.')
        if provider != 'marta-softpos':
            errors['provider'] = _('Unsupported local payment provider.')
        if result.get('ok') is not True or terminal_status != 'SUCCESS':
            errors['status'] = _('The local terminal result is not successful.')
        if not reference:
            errors['reference'] = _('The local terminal reference is required.')
        if not edge_operation_id or result_operation_id != edge_operation_id:
            errors['edgeOperationId'] = _('Terminal result does not match the Edge operation.')
        if charged_card_amount != int(card_amount or 0):
            errors['cardAmount'] = _('Terminal charged amount does not match the payment card amount.')
        if errors:
            raise ValidationError({'edgeProviderResult': errors})

        return {
            **result,
            'ok': True,
            'provider': provider,
            'status': terminal_status,
            'reference': reference,
            'cardAmount': charged_card_amount,
            'edgeOperationId': edge_operation_id,
            'trustedEdgeReplay': True,
            'replayed_at': timezone.now().isoformat(),
        }

    def _validate_shift(self, *, order, cash_shift):
        if cash_shift is None:
            raise ValidationError({'detail': _('Open a cashier shift before accepting payments.')})
        if cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': _('Only an open cashier shift can be used for payment.')})
        if cash_shift.cash_desk.restaurant_id != order.restaurant_id:
            raise ValidationError({'detail': _('Active cashier shift belongs to another restaurant.')})

    def _validate_payment_amount(self, *, order, amount):
        remaining_amount = self._remaining_amount(order=order)
        if remaining_amount <= 0:
            raise ValidationError({'amount': _('Order is already fully paid.')})
        if amount > remaining_amount:
            raise ValidationError({'amount': _('Payment amount cannot exceed the remaining total.')})

    def _apply_fiscal_breakdown(self, *, order, payment, amount=None, cash_amount=None, card_amount=None):
        amount = int(amount if amount is not None else payment.amount or 0)
        cash_amount = int(cash_amount if cash_amount is not None else payment.cash_amount or 0)
        card_amount = int(card_amount if card_amount is not None else payment.card_amount or 0)
        restricted_total = self._restricted_fiscal_total(order=order)

        fiscal_card_amount = max(card_amount, restricted_total)
        fiscal_card_amount = min(fiscal_card_amount, amount)
        fiscal_cash_amount = max(amount - fiscal_card_amount, 0)
        adjustment_reason = 'cash_forbidden_category' if restricted_total and (
            fiscal_cash_amount != cash_amount or fiscal_card_amount != card_amount
        ) else ''

        payment.fiscal_cash_amount = fiscal_cash_amount
        payment.fiscal_card_amount = fiscal_card_amount
        payment.fiscal_adjustment_reason = adjustment_reason
        payment.save(update_fields=['fiscal_cash_amount', 'fiscal_card_amount', 'fiscal_adjustment_reason', 'updated_at'])

    @staticmethod
    def _remaining_amount(*, order) -> int:
        paid_total = order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(total=Sum('amount')).get('total') or 0
        return max(0, int(order.total or 0) - int(paid_total or 0))

    @staticmethod
    def _succeeded_payment_totals(*, order) -> dict:
        return order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(
            amount=Sum('amount'),
            cash_amount=Sum('cash_amount'),
            card_amount=Sum('card_amount'),
        )

    def _restricted_fiscal_total(self, *, order) -> int:
        order_item_model = order.items.model
        order_items = list(
            order.items.exclude(status=order_item_model.Status.CANCELLED)
            .select_related('catalog_item', 'catalog_item__category')
            .order_by('created_at', 'id')
        )
        restricted_items = [item for item in order_items if is_catalog_item_cash_sale_forbidden(item)]
        if not restricted_items:
            return 0
        restricted_total = sum(int(item.line_total or 0) for item in restricted_items)
        service_fee = max(int(order.total or 0) - int(order.subtotal or 0), 0)
        if service_fee <= 0:
            return restricted_total
        subtotal = sum(int(item.line_total or 0) for item in order_items)
        if subtotal <= 0:
            return restricted_total + service_fee
        restricted_fee = int(
            (Decimal(service_fee) * Decimal(restricted_total) / Decimal(subtotal)).quantize(
                Decimal('1'),
                rounding=ROUND_HALF_UP,
            )
        )
        return restricted_total + restricted_fee

    def _complete_successful_payment(self, *, order, payment, received_by):
        if order.channel == Order.Channel.TAKEAWAY and order.status == Order.Status.OPEN:
            self.order_submission_service_class().submit(order)

        totals = self._succeeded_payment_totals(order=order)
        paid_total = int(totals.get('amount') or 0)
        is_fully_paid = paid_total >= int(order.total or 0)
        if is_fully_paid:
            self._apply_fiscal_breakdown(
                order=order,
                payment=payment,
                amount=paid_total,
                cash_amount=int(totals.get('cash_amount') or 0),
                card_amount=int(totals.get('card_amount') or 0),
            )
            self.state_service_class().close_order_after_payment(order=order, received_by=received_by)
        elif payment.register_fiscal:
            payment.register_fiscal = False
            payment.save(update_fields=['register_fiscal', 'updated_at'])

        receipts = []
        if is_fully_paid and payment.register_fiscal:
            receipt_results = self._issue_fiscal_receipts(order=order, payment=payment, opened_by=received_by)
            for receipt_result in receipt_results or []:
                receipts.append(self._create_fiscal_receipt(order=order, payment=payment, receipt_result=receipt_result))
        if is_fully_paid and not payment.register_fiscal:
            receipts.append(self._create_plain_receipt(order=order, payment=payment, created_by=received_by))
        logger.info(
            'Payment processed',
            extra={
                'order_id': str(order.pk),
                'payment_id': str(payment.pk),
                'payment_status': payment.status,
                'receipt_count': len(receipts),
            },
        )
        return {
            'payment': payment,
            'receipt': receipts[0] if receipts else None,
            'receipts': receipts,
            'order': order,
        }

    def _issue_fiscal_receipts(self, *, order, payment, opened_by, split_reasons=None):
        try:
            self.shift_service_class().ensure_fiscal_shift_open(
                restaurant=order.restaurant,
                opened_by=opened_by,
            )
        except Exception as error:
            return self._fiscal_shift_open_error_results(error=error, split_reasons=split_reasons)
        return issue_fiscal_receipts(order=order, payment=payment, split_reasons=split_reasons)

    @staticmethod
    def _fiscal_shift_open_error_results(*, error, split_reasons=None):
        def payload(split_reason=''):
            result = {
                'ok': False,
                'provider': '',
                'code': 'FISCAL_SHIFT_OPEN_FAILED',
                'detail': str(error),
                'fiscal_requested_at': timezone.now().isoformat(),
            }
            if split_reason:
                result['split_reason'] = split_reason
            return result

        if split_reasons:
            return [payload(str(split_reason or '')) for split_reason in split_reasons]
        return [payload()]

    @staticmethod
    def _should_submit_before_payment(*, order):
        return order.status == Order.Status.OPEN and order.channel != Order.Channel.TAKEAWAY

    @staticmethod
    def _positive_int(value, fallback):
        try:
            parsed = int(value or fallback)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed > 0 else fallback

    @staticmethod
    def _marta_pid(*, payment):
        pid = int(payment.id.int % JAVA_LONG_MAX)
        return pid or 1

    @classmethod
    def _normalize_marta_debug_payload(cls, value):
        if isinstance(value, list):
            return [cls._normalize_marta_debug_payload(item) for item in value]
        if not isinstance(value, dict):
            return value

        normalized = {}
        for key, item in value.items():
            normalized[key] = cls._normalize_marta_debug_payload(item)
        if 'http_status' in normalized and 'httpStatus' not in normalized:
            normalized['httpStatus'] = normalized['http_status']
        return normalized

    def _create_fiscal_receipt(self, *, order, payment, receipt_result: dict):
        status = Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED
        payload = self._receipt_payload_with_order_context(order=order, receipt_result=receipt_result)
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=status,
            provider=receipt_result.get('provider', ''),
            payload=payload,
            fiscal_requested_at=self._parse_payload_datetime(receipt_result.get('fiscal_requested_at')) or timezone.now(),
            fiscal_registered_at=self._parse_payload_datetime(receipt_result.get('fiscal_registered_at')) if status == Receipt.Status.SENT else None,
            original_paid_at=payment.paid_at,
            fiscal_error_code=str(receipt_result.get('code') or receipt_result.get('error_code') or ''),
            fiscal_error_message='' if status == Receipt.Status.SENT else str(receipt_result.get('detail') or receipt_result.get('message') or ''),
        )
        if status == Receipt.Status.SENT:
            attach_receipt_print_document(
                receipt=receipt,
                fiscal_result=receipt_result,
                created_by=payment.received_by,
            )
        return receipt

    @staticmethod
    def _create_plain_receipt(*, order, payment, created_by):
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.PLAIN,
            status=Receipt.Status.CREATED,
            provider='local-edge',
            payload={},
            original_paid_at=payment.paid_at,
        )
        attach_receipt_print_document(receipt=receipt, created_by=created_by)
        return receipt

    @staticmethod
    def _receipt_payload_with_order_context(*, order, receipt_result: dict):
        payload = dict(receipt_result or {})
        payload['order_number'] = order.order_number
        payload['order_label'] = build_order_label(order)
        payload['channel_label'] = OrderPaymentService._order_channel_label(order)
        payload['restaurant_name'] = order.restaurant.name
        payload['restaurant_legal_name'] = order.restaurant.legal_name or order.restaurant.name
        payload['restaurant_address'] = order.restaurant.address
        payload['restaurant_phone'] = order.restaurant.phone
        payload['restaurant_social'] = getattr(order.restaurant, 'social', '')
        payload['service_fee_percent'] = str(getattr(order.restaurant, 'service_fee_percent', 0) or 0)
        payload['table_label'] = OrderPaymentService._order_table_label(order)
        payload['cashier_name'] = order.cashier.full_name if order.cashier_id and order.cashier else ''
        payload['cashier_id'] = str(order.cashier_id or '')
        payload['waiter_name'] = order.opened_by.full_name if order.opened_by_id and order.opened_by else ''
        payload['order_note'] = order.note or ''
        if order.channel == Order.Channel.DELIVERY:
            payload['delivery_phone'] = order.delivery_phone or ''
            payload['delivery_address'] = order.delivery_address or ''
        return payload

    @staticmethod
    def _order_channel_label(order) -> str:
        if order.channel == Order.Channel.HALL:
            return 'Zalda'
        if order.channel == Order.Channel.DELIVERY:
            return 'Yetkazib berish'
        if order.channel == Order.Channel.ONLINE:
            return 'Online'
        return 'Zalda'

    @staticmethod
    def _order_table_label(order) -> str:
        if not order.table_session_id or not order.table_session:
            return ''
        table = getattr(order.table_session, 'table', None)
        return f"Stol: {table.name}" if table is not None else ''

    @staticmethod
    def _parse_payload_datetime(value):
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed


class PaymentFiscalRetryService:
    def retry(self, *, payment: Payment):
        if payment.status != Payment.Status.SUCCEEDED:
            raise ValidationError({'detail': _('Only successful payments can be sent to fiscal integration.')})

        sent_receipts = list(
            payment.receipts.filter(kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT).order_by('created_at')
        )
        pending_receipts = list(
            payment.receipts.filter(kind=Receipt.Kind.FISCAL)
            .exclude(status=Receipt.Status.SENT)
            .order_by('created_at')
        )
        if sent_receipts and not pending_receipts:
            for receipt in sent_receipts:
                if receipt.print_document_id is None:
                    attach_receipt_print_document(
                        receipt=receipt,
                        fiscal_result=receipt.payload or {},
                        created_by=payment.received_by,
                    )
            return {
                'payment': payment,
                'receipt': sent_receipts[0],
                'receipts': sent_receipts,
                'result': sent_receipts[0].payload or {},
                'results': [receipt.payload or {} for receipt in sent_receipts],
            }

        split_reasons = self._retry_split_reasons(sent_receipts=sent_receipts, pending_receipts=pending_receipts)
        receipts = []
        results = OrderPaymentService()._issue_fiscal_receipts(
            order=payment.order,
            payment=payment,
            opened_by=payment.received_by,
            split_reasons=split_reasons,
        )
        if not results or any(not result.get('ok') for result in results):
            return {
                'payment': payment,
                'receipt': None,
                'receipts': [],
                'result': results[0] if results else {},
                'results': results,
            }

        for index, receipt_result in enumerate(results):
            receipt = self._pick_existing_receipt(
                pending_receipts=pending_receipts,
                split_reason=str(receipt_result.get('split_reason') or ''),
                fallback_index=index,
            )
            receipts.append(self._persist_result(payment=payment, receipt=receipt, receipt_result=receipt_result))

        if not payment.register_fiscal:
            payment.register_fiscal = True
            payment.save(update_fields=['register_fiscal', 'updated_at'])

        return {
            'payment': payment,
            'receipt': receipts[0] if receipts else None,
            'receipts': receipts,
            'result': results[0] if results else {},
            'results': results,
        }

    def _retry_split_reasons(self, *, sent_receipts: list[Receipt], pending_receipts: list[Receipt]):
        if not sent_receipts:
            return None
        split_reasons = [
            str((receipt.payload or {}).get('split_reason') or '')
            for receipt in pending_receipts
            if str((receipt.payload or {}).get('split_reason') or '')
        ]
        if split_reasons:
            return list(dict.fromkeys(split_reasons))
        raise ValidationError({
            'detail': _(
                'This payment has partially registered fiscal receipts, but failed receipt split metadata is missing. '
                'Retry is blocked to avoid duplicate fiscal registration.'
            )
        })

    def _pick_existing_receipt(self, *, pending_receipts: list[Receipt], split_reason: str, fallback_index: int):
        for receipt in pending_receipts:
            payload = receipt.payload or {}
            if str(payload.get('split_reason') or '') == split_reason:
                pending_receipts.remove(receipt)
                return receipt
        if fallback_index < len(pending_receipts):
            return pending_receipts.pop(fallback_index)
        if pending_receipts:
            return pending_receipts.pop(0)
        return None

    def _persist_result(self, *, payment: Payment, receipt, receipt_result: dict):
        status = Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED
        payload = OrderPaymentService._receipt_payload_with_order_context(
            order=payment.order,
            receipt_result=receipt_result,
        )
        values = {
            'status': status,
            'provider': receipt_result.get('provider', ''),
            'payload': payload,
            'fiscal_requested_at': OrderPaymentService._parse_payload_datetime(receipt_result.get('fiscal_requested_at')) or timezone.now(),
            'fiscal_registered_at': OrderPaymentService._parse_payload_datetime(receipt_result.get('fiscal_registered_at')) if status == Receipt.Status.SENT else None,
            'original_paid_at': payment.paid_at,
            'fiscal_error_code': str(receipt_result.get('code') or receipt_result.get('error_code') or ''),
            'fiscal_error_message': '' if status == Receipt.Status.SENT else str(receipt_result.get('detail') or receipt_result.get('message') or ''),
        }
        if receipt is None:
            receipt = Receipt.objects.create(
                order=payment.order,
                payment=payment,
                kind=Receipt.Kind.FISCAL,
                **values,
            )
        else:
            for field, value in values.items():
                setattr(receipt, field, value)
            receipt.save(
                update_fields=[
                    'status',
                    'provider',
                    'payload',
                    'fiscal_requested_at',
                    'fiscal_registered_at',
                    'original_paid_at',
                    'fiscal_error_code',
                    'fiscal_error_message',
                    'updated_at',
                ]
            )
        if status == Receipt.Status.SENT:
            attach_receipt_print_document(
                receipt=receipt,
                fiscal_result=receipt_result,
                created_by=payment.received_by,
            )
        return receipt
