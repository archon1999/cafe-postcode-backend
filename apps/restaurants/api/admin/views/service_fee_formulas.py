"""Formula authoring tools. Preview never modifies an order or restaurant."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.service_fee_formulas import FormulaError, evaluate_formula
from common.service_fee_formulas.catalog import TEMPLATES, normalize_definition
from common.service_fee_formulas.language import SYSTEM_TYPES, VERSION
from apps.restaurants.models import ServiceFeePolicy
from apps.floor.models import Hall, DiningTable
from apps.inventory.ai import ai_available
from apps.restaurants.services.service_fee_ai import generate_formula_draft


class FormulaPreviewThrottle(UserRateThrottle):
    scope = 'service_fee_preview'
    rate = '120/min'


class FormulaAuthoringView(AdminPermissionRequiredMixin, APIView):
    # Formula parameter identifiers are code, not DTO keys: do not camelize them.
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]
    throttle_classes = [FormulaPreviewThrottle]


class FormulaCatalogView(FormulaAuthoringView):
    def get(self, request):
        get_request_restaurant(request)
        return Response({
            'version': VERSION,
            'templates': TEMPLATES,
            'variables': [{'name': name, 'type': kind} for name, kind in SYSTEM_TYPES.items()],
            'functions': [
                {'name': 'if', 'signature': 'if(condition, when_true, when_false)', 'description': 'Faqat tanlangan shart hisoblanadi.'},
                {'name': 'min', 'signature': 'min(a, b, ...)', 'description': 'Eng kichik qiymat.'},
                {'name': 'max', 'signature': 'max(a, b, ...)', 'description': 'Eng katta qiymat.'},
                {'name': 'abs', 'signature': 'abs(value)', 'description': 'Sonning moduli.'},
                {'name': 'floor', 'signature': 'floor(value, step = 1)', 'description': 'Qadamga pastga yaxlitlash.'},
                {'name': 'ceil', 'signature': 'ceil(value, step = 1)', 'description': 'Qadamga yuqoriga yaxlitlash.'},
                {'name': 'round', 'signature': 'round(value, step = 1, mode = "half_up")', 'description': 'Pulni belgilangan qadamga yaxlitlash.'},
                {'name': 'round_money', 'signature': 'round_money(value, step = 1, mode = "half_up")', 'description': 'round funksiyasining boshqa nomi.'},
                {'name': 'minutes_in', 'signature': 'minutes_in([start, end,] "HH:MM", "HH:MM")', 'description': 'Vaqt oralig‘iga tushgan haqiqiy daqiqalar; minimum qo‘llanmaydi.'},
                {'name': 'time_in', 'signature': 'time_in(timestamp, "HH:MM", "HH:MM")', 'description': 'Berilgan vaqt oraliqqa kirishini tekshiradi.'},
                {'name': 'add_minutes', 'signature': 'add_minutes(timestamp, integer_minutes)', 'description': 'Vaqtga butun daqiqalar qo‘shish; chegara ±366 kun.'},
            ],
            'rounding_modes': ['half_up', 'half_down', 'floor', 'ceil'],
            'default_timezone': 'Asia/Tashkent',
            'ai_available': ai_available(),
        })


class PreviewContextSerializer(serializers.Serializer):
    subtotal = serializers.IntegerField(min_value=0, max_value=2_147_483_647)
    guest_count = serializers.IntegerField(min_value=0, max_value=100000, default=1)
    # The runtime rejects naive timestamps; DateTimeField would silently localize them.
    started_at = serializers.CharField(max_length=64)
    calculated_at = serializers.CharField(max_length=64)


class FormulaPreviewSerializer(serializers.Serializer):
    definition = serializers.JSONField()
    context = PreviewContextSerializer()


class FormulaPreviewView(FormulaAuthoringView):
    def post(self, request):
        get_request_restaurant(request)
        serializer = FormulaPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            definition = normalize_definition(serializer.validated_data['definition'])
            result = evaluate_formula(
                definition['source'], definition['parameters'],
                timezone_name=definition['timezone'], **serializer.validated_data['context'],
            )
        except FormulaError as error:
            return Response({'valid': False, 'errors': [error.as_dict()]}, status=400)
        return Response({'valid': True, 'definition': definition, 'result': result})


class FormulaAIThrottle(UserRateThrottle):
    scope = 'service_fee_ai'
    rate = '6/min'


class FormulaAIInputSerializer(serializers.Serializer):
    text = serializers.CharField(min_length=5, max_length=4000)
    timezone = serializers.CharField(default='Asia/Tashkent', max_length=100)


class FormulaAIDraftView(FormulaAuthoringView):
    throttle_classes = [FormulaAIThrottle]

    def post(self, request):
        get_request_restaurant(request)
        serializer = FormulaAIInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            normalize_definition({'source': '0', 'timezone': data['timezone']})
        except FormulaError as error:
            raise serializers.ValidationError({'timezone': str(error)}) from None
        return Response(generate_formula_draft(data['text'], data['timezone']))


class ServiceFeePolicySerializer(serializers.ModelSerializer):
    revision = serializers.CharField(read_only=True)
    expected_revision = serializers.CharField(write_only=True, required=False, max_length=64)

    class Meta:
        model = ServiceFeePolicy
        fields = ('id', 'name', 'definition', 'is_active', 'revision', 'expected_revision', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        expected_revision = attrs.pop('expected_revision', None)
        if self.instance is not None and expected_revision != self.instance.revision:
            raise serializers.ValidationError({'expected_revision': 'Tarif o‘zgargan. Yangilangan nusxani qayta oching.'})
        raw = attrs.get('definition', self.instance.definition if self.instance else {})
        name = attrs.get('name', self.instance.name if self.instance else '')
        if not isinstance(raw, dict):
            raise serializers.ValidationError({'definition': 'Formula definition must be an object.'})
        try:
            attrs['definition'] = normalize_definition({**raw, 'name': name})
        except FormulaError as error:
            raise serializers.ValidationError({'definition': str(error)}) from None
        return attrs


class ServiceFeePolicyListView(FormulaAuthoringView):
    def get(self, request):
        restaurant = get_request_restaurant(request)
        policies = ServiceFeePolicy.objects.filter(restaurant=restaurant)
        return Response(ServiceFeePolicySerializer(policies, many=True).data)

    def post(self, request):
        restaurant = get_request_restaurant(request)
        serializer = ServiceFeePolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(restaurant=restaurant)
        return Response(serializer.data, status=201)


class ServiceFeePolicyDetailView(FormulaAuthoringView):
    def get(self, request, pk):
        policy = get_object_or_404(ServiceFeePolicy, pk=pk, restaurant=get_request_restaurant(request))
        return Response(ServiceFeePolicySerializer(policy).data)

    @transaction.atomic
    def patch(self, request, pk):
        policy = get_object_or_404(ServiceFeePolicy.objects.select_for_update(), pk=pk, restaurant=get_request_restaurant(request))
        serializer = ServiceFeePolicySerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class FormulaAssignmentSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=('restaurant', 'hall', 'table'))
    target_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=('none', 'percentage', 'formula'), required=False)
    percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=1, max_value=99, required=False)
    formula = serializers.JSONField(required=False)
    policy_id = serializers.UUIDField(allow_null=True, required=False)
    expected_revision = serializers.CharField(required=False, max_length=64)

    def validate(self, attrs):
        if 'mode' not in attrs and 'policy_id' not in attrs:
            raise serializers.ValidationError({'mode': 'Select none, percentage or formula.'})
        mode = attrs.setdefault('mode', 'formula' if attrs.get('policy_id') else 'none')
        if mode == 'percentage':
            if 'percent' not in attrs:
                raise serializers.ValidationError({'percent': 'Enter a percentage.'})
            if attrs['scope'] != 'restaurant' and attrs['percent'] % 1:
                raise serializers.ValidationError({'percent': 'Hall and table percentages must be whole numbers.'})
        if mode == 'formula' and not attrs.get('policy_id'):
            try:
                attrs['formula'] = normalize_definition(attrs.get('formula'))
            except FormulaError as error:
                raise serializers.ValidationError({'formula': str(error)}) from None
        return attrs


class FormulaAssignmentsView(FormulaAuthoringView):
    @staticmethod
    def targets(restaurant):
        yield 'restaurant', restaurant
        for hall in Hall.objects.filter(zone_or_cabin__restaurant=restaurant).order_by('name'):
            yield 'hall', hall
        for table in DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant).select_related('hall').order_by('hall__name', 'table_number'):
            yield 'table', table

    def get(self, request):
        restaurant = get_request_restaurant(request)
        return Response([{
            'scope': scope, 'id': str(target.pk), 'name': target.name,
            'hall_name': target.hall.name if scope == 'table' else None,
            'enabled': target.service_fee_enabled, 'mode': target.service_fee_mode,
            'percent': str(target.service_fee_percent), 'hourly_rate': target.service_fee_hourly_rate,
            'formula': target.service_fee_formula,
        } for scope, target in self.targets(restaurant)])

    @transaction.atomic
    def post(self, request):
        restaurant = get_request_restaurant(request)
        serializer = FormulaAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        from apps.restaurants.models import Restaurant
        querysets = {
            'restaurant': Restaurant.objects.filter(pk=restaurant.pk),
            'hall': Hall.objects.filter(zone_or_cabin__restaurant=restaurant),
            'table': DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant),
        }
        target = get_object_or_404(querysets[data['scope']].select_for_update(), pk=data['target_id'])
        definition = {}
        if data['mode'] == 'formula' and data.get('policy_id') is not None:
            policy = get_object_or_404(ServiceFeePolicy.objects.select_for_update(), pk=data['policy_id'], restaurant=restaurant, is_active=True)
            if data.get('expected_revision') != policy.revision:
                raise serializers.ValidationError({'expected_revision': 'Tarif yangilangan. Qayta tanlang.'})
            definition = normalize_definition(policy.definition)
            definition['policy_id'] = str(policy.pk)
            definition['policy_revision'] = policy.revision
        elif data['mode'] == 'formula':
            definition = data['formula']
        target.service_fee_formula = definition
        target.service_fee_mode = 'formula' if definition else 'percentage'
        target.service_fee_enabled = data['mode'] != 'none'
        target.service_fee_percent = data['percent'] if data['mode'] == 'percentage' else 0
        target.service_fee_hourly_rate = 0
        target.save(update_fields=['service_fee_formula', 'service_fee_mode', 'service_fee_enabled',
                                   'service_fee_percent', 'service_fee_hourly_rate', 'updated_at'])
        return Response({'scope': data['scope'], 'id': str(target.pk), 'formula': definition,
                         'enabled': target.service_fee_enabled, 'mode': data['mode'],
                         'percent': str(target.service_fee_percent)})
