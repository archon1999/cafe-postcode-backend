from rest_framework import serializers

from apps.organizations.models import Branch


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = (
            'id',
            'name',
            'address',
            'phone',
            'legal_name',
            'tax_number',
            'vat_enabled',
            'service_fee_percent',
            'is_default',
        )
        validators = []
