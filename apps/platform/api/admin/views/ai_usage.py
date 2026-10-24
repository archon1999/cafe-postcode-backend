"""Superadmin-only, bounded read views over metadata-only AI accounting."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.models import AIUsageLog
from common.api.admin_permissions import ADMIN_PERMISSION_CLASSES
from common.api.permissions import IsAdmin

REPORT_ZONE = ZoneInfo('Asia/Tashkent')
GROUP_LIMIT = 100
ORDERING = {
    'created_at', '-created_at', 'duration_ms', '-duration_ms',
    'total_tokens', '-total_tokens', 'estimated_cost_usd', '-estimated_cost_usd',
}
AGGREGATES = {
    'request_count': Count('id'),
    'success_count': Count('id', filter=Q(status='success')),
    'error_count': Count('id', filter=Q(status='error')),
    'incoming': Sum('input_tokens'), 'cached': Sum('cached_input_tokens'),
    'outgoing': Sum('output_tokens'), 'tokens': Sum('total_tokens'),
    'cost': Sum('estimated_cost_usd'),
    'priced': Count('id', filter=Q(estimated_cost_usd__isnull=False)),
    'missing': Count('id', filter=Q(input_tokens__isnull=True) | Q(output_tokens__isnull=True) | Q(total_tokens__isnull=True)),
    'average_duration': Avg('duration_ms'),
}


class AwareTimestamp(serializers.DateTimeField):
    def to_internal_value(self, value):
        if isinstance(value, str):
            try:
                parsed = parse_datetime(value)
            except ValueError:
                parsed = None
            if parsed is not None and timezone.is_naive(parsed):
                raise serializers.ValidationError('Include a timezone offset or Z.')
        return super().to_internal_value(value)


class UsageFilters(serializers.Serializer):
    from_date = AwareTimestamp(required=False)
    to_date = AwareTimestamp(required=False)
    restaurant_id = serializers.UUIDField(required=False)
    business_partner_id = serializers.UUIDField(required=False)
    model = serializers.CharField(max_length=120, required=False)
    feature = serializers.ChoiceField(choices=AIUsageLog.Feature.values, required=False)
    status = serializers.ChoiceField(choices=AIUsageLog.Status.values, required=False)
    search = serializers.CharField(max_length=120, required=False)
    page = serializers.IntegerField(min_value=1, max_value=1000000, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    ordering = serializers.ChoiceField(choices=sorted(ORDERING), default='-created_at')


def _metrics(row):
    count, priced = row.get('request_count', 0), row.get('priced', 0)
    cost = row.get('cost')
    return {
        'requestCount': count, 'successCount': row.get('success_count', 0), 'errorCount': row.get('error_count', 0),
        'inputTokens': int(row.get('incoming') or 0), 'cachedInputTokens': int(row.get('cached') or 0),
        'outputTokens': int(row.get('outgoing') or 0), 'totalTokens': int(row.get('tokens') or 0),
        'estimatedCostUsd': str(cost) if cost is not None else ('0' if count == 0 else None),
        'pricedRequestCount': priced, 'unpricedRequestCount': count - priced,
        'missingUsageCount': row.get('missing', 0),
        'averageDurationMs': round(float(row['average_duration']), 2) if row.get('average_duration') is not None else None,
    }


def _filters(request):
    data = {('from_date' if key == 'from' else 'to_date' if key == 'to' else key): value
            for key, value in request.query_params.items() if value != ''}
    allowed = set(UsageFilters().fields)
    if set(data) - allowed:
        raise serializers.ValidationError({'filters': 'Unknown filter parameter.'})
    serializer = UsageFilters(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    end = data.get('to_date', timezone.now())
    start = data.get('from_date', end - timedelta(days=30))
    if start >= end or end - start > timedelta(days=366):
        raise serializers.ValidationError({'from': 'Use a positive range of at most 366 days.'})
    data['from_date'], data['to_date'] = start, end
    return data


def _queries(request):
    filters = _filters(request)
    base = AIUsageLog.objects.filter(created_at__gte=filters['from_date'], created_at__lt=filters['to_date'])
    for key in ('restaurant_id', 'business_partner_id'):
        if key in filters:
            base = base.filter(**{key: filters[key]})
    query = base
    for key in ('model', 'feature', 'status'):
        if key in filters:
            query = query.filter(**{key: filters[key]})
    if filters.get('search'):
        term = filters['search']
        query = query.filter(Q(restaurant_name__icontains=term) | Q(business_partner_name__icontains=term)
                             | Q(user_name__icontains=term) | Q(model__icontains=term)
                             | Q(feature__icontains=term) | Q(request_id__icontains=term)
                             | Q(error_code__icontains=term))
    return filters, base, query


class AIUsageView(APIView):
    permission_classes = [*ADMIN_PERMISSION_CLASSES, IsAdmin]
    http_method_names = ['get', 'head', 'options']


class AIUsageSummaryView(AIUsageView):
    def get(self, request):
        filters, base, query = _queries(request)
        branches = list(query.order_by().values('restaurant_id', 'business_partner_id').annotate(
            restaurant_label=Max('restaurant_name'), partner_label=Max('business_partner_name'),
            **AGGREGATES).order_by('-request_count', 'restaurant_label')[:GROUP_LIMIT + 1])
        models = list(query.order_by().values('model').annotate(**AGGREGATES).order_by('-request_count', 'model')[:GROUP_LIMIT + 1])
        features = list(query.order_by().values('feature').annotate(**AGGREGATES).order_by('-request_count', 'feature')[:GROUP_LIMIT + 1])
        daily = {row['date']: row for row in query.order_by().annotate(date=TruncDate('created_at', tzinfo=REPORT_ZONE)).values('date').annotate(**AGGREGATES)}
        day = filters['from_date'].astimezone(REPORT_ZONE).date()
        last = (filters['to_date'] - timedelta(microseconds=1)).astimezone(REPORT_ZONE).date()
        trend = []
        while day <= last:
            trend.append({'date': day.isoformat(), **_metrics(daily.get(day, {}))})
            day += timedelta(days=1)
        started = AIUsageLog.objects.aggregate(first=Min('created_at'))['first']
        return Response({
            'from': filters['from_date'].isoformat(), 'to': filters['to_date'].isoformat(),
            'trackingStartedAt': started.isoformat() if started else None,
            'totals': _metrics(query.aggregate(**AGGREGATES)), 'trend': trend,
            'branches': [{
                'restaurantId': str(row['restaurant_id']) if row['restaurant_id'] else None,
                'restaurantName': row['restaurant_label'] or None,
                'businessPartnerId': str(row['business_partner_id']) if row['business_partner_id'] else None,
                'businessPartnerName': row['partner_label'] or None, **_metrics(row),
            } for row in branches[:GROUP_LIMIT]],
            'models': [{'model': row['model'], **_metrics(row)} for row in models[:GROUP_LIMIT]],
            'features': [{'feature': row['feature'], **_metrics(row)} for row in features[:GROUP_LIMIT]],
            'filterOptions': {
                'models': list(base.order_by('model').values_list('model', flat=True).distinct()[:1000]),
                'features': list(base.order_by('feature').values_list('feature', flat=True).distinct()),
                'statuses': list(AIUsageLog.Status.values),
            },
            'groupsTruncated': any(len(rows) > GROUP_LIMIT for rows in (branches, models, features)),
        })


class AIUsageRequestsView(AIUsageView):
    def get(self, request):
        filters, _, query = _queries(request)
        field = filters['ordering'].lstrip('-')
        direction = F(field).desc(nulls_last=True) if filters['ordering'].startswith('-') else F(field).asc(nulls_last=True)
        count = query.count()
        offset = (filters['page'] - 1) * filters['page_size']
        rows = query.order_by(direction, '-id')[offset:offset + filters['page_size']]
        return Response({
            'count': count, 'page': filters['page'], 'pageSize': filters['page_size'],
            'results': [{
                'id': str(row.pk), 'createdAt': row.created_at.isoformat(),
                'restaurantId': str(row.restaurant_id) if row.restaurant_id else None,
                'restaurantName': row.restaurant_name or None,
                'businessPartnerId': str(row.business_partner_id) if row.business_partner_id else None,
                'businessPartnerName': row.business_partner_name or None,
                'userId': str(row.user_id) if row.user_id else None, 'userName': row.user_name or None,
                'feature': row.feature, 'provider': row.provider, 'model': row.model, 'status': row.status,
                'inputTokens': row.input_tokens, 'cachedInputTokens': row.cached_input_tokens,
                'outputTokens': row.output_tokens, 'totalTokens': row.total_tokens,
                'estimatedCostUsd': str(row.estimated_cost_usd) if row.estimated_cost_usd is not None else None,
                'durationMs': row.duration_ms, 'requestId': row.request_id or None,
                'providerStatus': row.provider_status or None, 'errorCode': row.error_code or None,
                'errorSummary': row.error_summary or None,
            } for row in rows],
        })
