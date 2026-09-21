from rest_framework import serializers

from common.service_fee_formulas import FormulaError
from common.service_fee_formulas.catalog import normalize_definition


class ServiceFeeFormulaField(serializers.JSONField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value == {}:
            return value
        try:
            return normalize_definition(value)
        except FormulaError as error:
            raise serializers.ValidationError(str(error)) from None
