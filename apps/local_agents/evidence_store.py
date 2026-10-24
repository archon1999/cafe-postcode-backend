"""Versioned response references. No business command is ever dispatched here."""
import copy
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from django.db import connection

from apps.local_agents.models import AgentEvidencePayload, AgentEvidencePolicy

REFERENCE_KEY = '__agent_evidence_body__'
MIN_BODY_BYTES = 1024
_cache = ContextVar('agent_evidence_request_cache', default=None)


class EvidenceUnavailable(Exception):
    """The idempotency guard still exists; fail closed instead of reapplying."""


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def checksum(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def is_reference(body):
    # Treat malformed reserved markers as errors, never as a business response.
    return isinstance(body, dict) and REFERENCE_KEY in body


def body_reference(payload):
    return {REFERENCE_KEY: {'v': 1, 'id': str(payload.pk), 'sha256': payload.checksum}}


def reference_identity(body):
    try:
        reference = body[REFERENCE_KEY]
        if (set(body) != {REFERENCE_KEY} or set(reference) != {'v', 'id', 'sha256'}
                or reference['v'] != 1 or len(reference['sha256']) != 64):
            raise ValueError
        return UUID(reference['id']), reference['sha256']
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise EvidenceUnavailable('Invalid evidence reference.') from error


def store_body(*, restaurant_id, operation_id, body, force=False):
    if is_reference(body):
        # Only internal callers pass references; do not nest them.
        reference_identity(body)
        return copy.deepcopy(body)
    if not force and not AgentEvidencePolicy.objects.filter(
        restaurant_id=restaurant_id, writes_enabled=True,
    ).exists():
        return copy.deepcopy(body)
    encoded = canonical_bytes(body)
    if len(encoded) < MIN_BODY_BYTES:
        return copy.deepcopy(body)
    digest = hashlib.sha256(encoded).hexdigest()
    payload, _ = AgentEvidencePayload.objects.get_or_create(
        restaurant_id=restaurant_id, operation_id=operation_id, checksum=digest,
        defaults={'byte_length': len(encoded), 'content': {'body': body}},
    )
    if payload.byte_length != len(encoded):
        raise EvidenceUnavailable('Evidence length mismatch.')
    if payload.content is not None and payload.content != {'body': body}:
        raise EvidenceUnavailable('Existing immutable evidence differs from its content hash.')
    # An already cold immutable payload stays cold; never overwrite its contents.
    return body_reference(payload)


def store_result(*, restaurant_id, operation_id, result, force=False):
    stored = copy.deepcopy(result)
    if stored.get('ok') and 'body' in stored:
        stored['body'] = store_body(
            restaurant_id=restaurant_id, operation_id=operation_id, body=stored['body'], force=force,
        )
    return stored


@contextmanager
def evidence_cache():
    current = _cache.get()
    token = _cache.set({}) if current is None else None
    try:
        yield
    finally:
        if token is not None:
            _cache.reset(token)


def resolve_body(*, restaurant_id, operation_id, body):
    if not is_reference(body):
        return copy.deepcopy(body)
    payload_id, digest = reference_identity(body)
    cache_key = (str(restaurant_id), operation_id, str(payload_id), digest)
    cache = _cache.get()
    if cache is not None and cache_key in cache:
        return copy.deepcopy(cache[cache_key])
    payload = AgentEvidencePayload.objects.select_related('archive').filter(
        pk=payload_id, restaurant_id=restaurant_id, operation_id=operation_id, checksum=digest,
    ).first()
    if payload is None:
        raise EvidenceUnavailable('Evidence not found in this restaurant/operation.')
    content = payload.content
    if content is None:
        # Includes filesystem I/O: never wait for an external store under DB locks.
        if connection.in_atomic_block:
            raise EvidenceUnavailable('Cold evidence was not prefetched before the transaction.')
        from apps.local_agents.evidence_archive import read_archive
        if payload.archive_id is None:
            raise EvidenceUnavailable('Cold evidence has no verified archive.')
        bundle_key = ('bundle', str(payload.archive_id), payload.archive.checksum)
        cached_bundle = cache.get(bundle_key) if cache is not None else None
        if isinstance(cached_bundle, EvidenceUnavailable):
            raise cached_bundle
        if cached_bundle is None:
            # One bounded bundle cache per HTTP batch. Reconnecting Agents often
            # replay many operations from the same old bundle.
            if cache is not None:
                for key in list(cache):
                    if key[0] == 'bundle':
                        del cache[key]
            try:
                cached_bundle = read_archive(payload.archive)
            except EvidenceUnavailable as error:
                if cache is not None:
                    cache[bundle_key] = error
                raise
            if cache is not None:
                cache[bundle_key] = cached_bundle
        records = cached_bundle
        content = records.get(str(payload.pk))
    if (not isinstance(content, dict) or set(content) != {'body'}
            or checksum(content['body']) != digest
            or len(canonical_bytes(content['body'])) != payload.byte_length):
        raise EvidenceUnavailable('Evidence checksum/length mismatch.')
    value = content['body']
    if cache is not None:
        body_keys = [key for key in cache if key[0] != 'bundle']
        if len(body_keys) >= 32:
            del cache[body_keys[0]]
        cache[cache_key] = copy.deepcopy(value)
    return copy.deepcopy(value)


def resolve_result(*, restaurant_id, operation_id, result):
    resolved = copy.deepcopy(result)
    if 'body' in resolved:
        resolved['body'] = resolve_body(restaurant_id=restaurant_id, operation_id=operation_id, body=resolved['body'])
    return resolved


def unavailable_result(operation_id):
    from apps.local_agents.mutation_results import mutation_error_result
    return mutation_error_result(
        operation_id=operation_id, response_status=503, retryable=True,
        code='EVIDENCE_TEMPORARILY_UNAVAILABLE',
        error='Original response is temporarily unavailable; the operation has not been executed again.',
    )
