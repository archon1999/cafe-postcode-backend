import json

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model

Payment = get_payment_model()


class EdgePaymentResultsMixin:
    @staticmethod
    def _validated_edge_provider_result(
        *, result, method, card_amount, edge_operation_id
    ):
        if not isinstance(result, dict):
            raise ValidationError(
                {"edgeProviderResult": _("Terminal result must be an object.")}
            )
        provider = str(result.get("provider") or "").strip()
        terminal_status = str(result.get("status") or "").strip().upper()
        reference = str(result.get("reference") or "").strip()
        result_operation_id = str(
            result.get("edgeOperationId") or result.get("edge_operation_id") or ""
        ).strip()
        try:
            charged_card_amount = int(
                result.get("cardAmount") or result.get("card_amount") or 0
            )
        except (TypeError, ValueError):
            charged_card_amount = 0

        errors = {}
        if method not in {Payment.Method.CARD, Payment.Method.MIXED}:
            errors["method"] = _(
                "A terminal result is valid only for card or mixed payments."
            )
        if provider != "marta-softpos":
            errors["provider"] = _("Unsupported local payment provider.")
        if result.get("ok") is not True or terminal_status != "SUCCESS":
            errors["status"] = _("The local terminal result is not successful.")
        if not reference:
            errors["reference"] = _("The local terminal reference is required.")
        if not edge_operation_id or result_operation_id != edge_operation_id:
            errors["edgeOperationId"] = _(
                "Terminal result does not match the Edge operation."
            )
        if charged_card_amount != int(card_amount or 0):
            errors["cardAmount"] = _(
                "Terminal charged amount does not match the payment card amount."
            )
        if errors:
            raise ValidationError({"edgeProviderResult": errors})

        return {
            **result,
            "ok": True,
            "provider": provider,
            "status": terminal_status,
            "reference": reference,
            "cardAmount": charged_card_amount,
            "edgeOperationId": edge_operation_id,
            "trustedEdgeReplay": True,
            "replayed_at": timezone.now().isoformat(),
        }

    @staticmethod
    def _parse_edge_fiscal_results_json(value):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {"edgeFiscalResults": _("Fiscal results JSON is invalid.")}
            ) from error
        return parsed

    @staticmethod
    def _validated_edge_fiscal_results(
        *, results, cash_desk, register_fiscal, expected_amount, allow_partial=False
    ):
        if not register_fiscal:
            raise ValidationError(
                {"edgeFiscalResults": _("Fiscal results require fiscal registration.")}
            )
        if not isinstance(results, list) or not 1 <= len(results) <= 4:
            raise ValidationError(
                {"edgeFiscalResults": _("Provide between one and four fiscal results.")}
            )

        integration = (
            getattr(cash_desk, "fiscal_integration", None)
            if cash_desk is not None
            else None
        )
        expected_provider = str(getattr(integration, "provider", "") or "").strip()
        if not expected_provider:
            raise ValidationError(
                {
                    "edgeFiscalResults": _(
                        "Fiscal integration is not configured for the active cash desk."
                    )
                }
            )

        normalized = []
        successful_fiscal_total = 0
        successful_count = 0
        for result in results:
            if not isinstance(result, dict):
                raise ValidationError(
                    {"edgeFiscalResults": _("Each fiscal result must be an object.")}
                )
            provider = str(result.get("provider") or "").strip()
            if provider != expected_provider:
                raise ValidationError(
                    {
                        "edgeFiscalResults": _(
                            "Fiscal result provider does not match the active cash desk."
                        )
                    }
                )
            if not isinstance(result.get("ok"), bool):
                raise ValidationError(
                    {
                        "edgeFiscalResults": _(
                            "Each fiscal result must contain a boolean ok field."
                        )
                    }
                )
            if result.get("ok"):
                successful_count += 1
                if not str(result.get("terminal_id") or "").strip():
                    raise ValidationError(
                        {
                            "edgeFiscalResults": _(
                                "Successful fiscal result requires terminal_id."
                            )
                        }
                    )
                if not str(result.get("receipt_number") or "").strip():
                    raise ValidationError(
                        {
                            "edgeFiscalResults": _(
                                "Successful fiscal result requires receipt_number."
                            )
                        }
                    )
                request_payload = (
                    result.get("request")
                    if isinstance(result.get("request"), dict)
                    else {}
                )
                receipt_payload = (
                    request_payload.get("receipt")
                    if isinstance(request_payload.get("receipt"), dict)
                    else {}
                )
                normalized_tenders = {
                    str(key).lstrip("_").replace("_", "").lower(): value
                    for key, value in receipt_payload.items()
                }
                try:
                    received_cash = int(normalized_tenders.get("receivedcash") or 0)
                    received_card = int(normalized_tenders.get("receivedcard") or 0)
                except (TypeError, ValueError) as error:
                    raise ValidationError(
                        {
                            "edgeFiscalResults": _(
                                "Fiscal receipt tender amounts are invalid."
                            )
                        }
                    ) from error
                if received_cash < 0 or received_card < 0:
                    raise ValidationError(
                        {
                            "edgeFiscalResults": _(
                                "Fiscal receipt tender amounts cannot be negative."
                            )
                        }
                    )
                successful_fiscal_total += received_cash + received_card
            normalized.append(dict(result))
        if (
            successful_count
            and (successful_fiscal_total > int(expected_amount or 0) * 100
                 or (successful_fiscal_total != int(expected_amount or 0) * 100
                     and not allow_partial and all(result.get('ok') for result in normalized)))
        ):
            raise ValidationError(
                {
                    "edgeFiscalResults": _(
                        "Fiscal receipt amount does not match the order total."
                    )
                }
            )
        return normalized
