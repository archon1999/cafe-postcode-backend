from common.service_fee_formulas import FormulaError


class ServiceFeeOrderRepresentationMixin:
    """An invalid quote must not prevent reading or correcting an open order."""

    def _fee_value(self, obj, calculate, *, fallback=None):
        try:
            return calculate(as_of=self._service_fee_as_of(obj))
        except FormulaError:
            return fallback

    def get_service_fee_error(self, obj):
        try:
            obj.get_service_fee_amount(as_of=self._service_fee_as_of(obj))
        except FormulaError as error:
            return {'code': 'SERVICE_FEE_FORMULA_ERROR', 'message': str(error)}
        return None

