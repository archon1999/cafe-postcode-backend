"""Verified Standard API estimates; exact model IDs and immutable row snapshots."""
import json
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings

MAX_TOKENS = 9_000_000_000_000_000
LONG_CONTEXT_INPUT_THRESHOLD = 272000
PRICING_SOURCE_URL = 'https://developers.openai.com/api/docs/pricing'
PRICING_VERIFIED_AT = '2026-10-24'
RATE_KEYS = ('input', 'cached_input', 'output')

# USD per one million tokens. Long-context prices apply to the whole request
# when its actual input count exceeds the documented threshold (cached included).
STANDARD_RATE_CARD = {
    'gpt-5.6-luna': {'short': ('0.20', '0.02', '1.20'), 'long': ('0.40', '0.04', '1.80')},
    'gpt-5.6-terra': {'short': ('2', '0.20', '12'), 'long': ('4', '0.40', '18')},
    'gpt-5.6-sol': {'short': ('4', '0.40', '20'), 'long': ('8', '0.80', '30')},
}


def complete_token_usage(usage):
    """Reject missing, malformed or inconsistent counts, without inventing zeros."""
    try:
        incoming, cached, outgoing, total = (
            usage[key] for key in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens')
        )
    except (KeyError, TypeError):
        return None
    if any(type(value) is not int or not 0 <= value <= MAX_TOKENS for value in (incoming, cached, outgoing, total)):
        return None
    if cached > incoming or incoming + outgoing != total:
        return None
    return incoming, cached, outgoing


def _rates(model, incoming):
    configured = getattr(settings, 'AI_USAGE_PRICING_USD_PER_MILLION', None)
    if configured is None:
        configured = os.getenv('AI_USAGE_PRICING_USD_PER_MILLION', '')
    if isinstance(configured, str):
        # An absent override enables defaults. Invalid explicit configuration
        # remains unpriced instead of silently overriding an operator's intent.
        if not configured:
            configured = {}
        elif len(configured) <= 65536:
            configured = json.loads(configured)
        else:
            return None, {}
    if not isinstance(configured, dict):
        return None, {}
    if model in configured:
        rates = configured[model]
        return rates, {'source': 'operator_override', 'context_tier': 'custom', 'unit': 'usd_per_million_tokens'}
    tiers = STANDARD_RATE_CARD.get(model)
    if tiers is None:
        return None, {}
    tier = 'long' if incoming > LONG_CONTEXT_INPUT_THRESHOLD else 'short'
    return dict(zip(RATE_KEYS, tiers[tier], strict=True)), {
        'source': 'openai_standard', 'source_url': PRICING_SOURCE_URL,
        'verified_at': PRICING_VERIFIED_AT, 'context_tier': tier,
        'long_context_input_threshold': LONG_CONTEXT_INPUT_THRESHOLD, 'unit': 'usd_per_million_tokens',
    }


def estimated_cost(model, usage):
    counts = complete_token_usage(usage)
    if counts is None or not isinstance(model, str):
        return None, {}
    incoming, cached, outgoing = counts
    try:
        rates, provenance = _rates(model, incoming)
        if not isinstance(rates, dict):
            return None, {}
        prices = {key: Decimal(str(rates[key])) for key in RATE_KEYS}
        if any(not value.is_finite() or value < 0 or value > 1000000 for value in prices.values()):
            return None, {}
        cost = ((incoming - cached) * prices['input'] + cached * prices['cached_input'] + outgoing * prices['output']) / Decimal(1000000)
        if cost >= Decimal('1000000000000'):
            return None, {}
        snapshot = {**{key: str(value) for key, value in prices.items()}, **provenance}
        return cost.quantize(Decimal('0.000000000001'), rounding=ROUND_HALF_UP), snapshot
    except (ValueError, TypeError, KeyError, InvalidOperation):
        return None, {}
