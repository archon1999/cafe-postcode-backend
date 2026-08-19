import base64
import hashlib
import json
import os
import time
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.devices.crypto import device_request_message
from apps.devices.models import Device, SecurityEvent
from apps.local_agents.models import LocalAgent, hash_agent_token
from apps.restaurants.models import Restaurant


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


class LocalAgentSecurityEventBatchTests(APITestCase):
    path = '/api/v1/local-agent/security-events/batch/'

    def setUp(self):
        cache.clear()
        self.restaurant = Restaurant.objects.create(name='Audited restaurant')
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.device = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.LOCAL_AGENT,
            name='Audited agent',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key=_b64url(public_key),
            public_key_fingerprint=hashlib.sha256(public_key).hexdigest(),
            status=Device.Status.ACTIVE,
            paired_at=timezone.now(),
            lease_expires_at=timezone.now() + timedelta(days=1),
        )
        self.agent = LocalAgent.objects.create(
            restaurant=self.restaurant,
            device=self.device,
            name='Audited agent',
            token_hash=hash_agent_token('cpa_legacy-audit-token'),
            is_active=True,
        )

    def event(self, **overrides):
        value = {
            'id': '11111111-1111-4111-8111-111111111111',
            'eventType': 'LOCAL_PIN_FAILED',
            'terminalId': 'pos-terminal-1',
            'sourceHash': 'a' * 64,
            'reason': 'invalid_pin_or_policy',
            'count': 3,
            'occurredAt': timezone.now().isoformat(),
        }
        value.update(overrides)
        return value

    def signed_post(self, payload):
        body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        timestamp = int(time.time())
        nonce = _b64url(os.urandom(24))
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = device_request_message(
            method='POST',
            request_target=self.path,
            device_id=self.device.pk,
            timestamp=timestamp,
            nonce=nonce,
            body_sha256=body_hash,
        )
        return self.client.generic(
            'POST',
            self.path,
            body,
            content_type='application/json',
            HTTP_X_DEVICE_ID=str(self.device.pk),
            HTTP_X_DEVICE_TIMESTAMP=str(timestamp),
            HTTP_X_DEVICE_NONCE=nonce,
            HTTP_X_DEVICE_CONTENT_SHA256=body_hash,
            HTTP_X_DEVICE_SIGNATURE=_b64url(self.private_key.sign(canonical.encode('utf-8'))),
        )

    def test_signed_batch_is_tenant_device_bound_sanitized_and_idempotent(self):
        payload = {'events': [self.event()]}

        first = self.signed_post(payload)
        second = self.signed_post(payload)

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.data['acceptedIds'], ['11111111-1111-4111-8111-111111111111'])
        self.assertEqual(SecurityEvent.objects.count(), 1)
        event = SecurityEvent.objects.get()
        self.assertEqual(event.restaurant, self.restaurant)
        self.assertEqual(event.device, self.device)
        self.assertEqual(event.severity, SecurityEvent.Severity.MEDIUM)
        self.assertEqual(event.result, 'DENIED')
        self.assertEqual(event.metadata['terminalId'], 'pos-terminal-1')
        self.assertEqual(event.metadata['sourceHash'], 'a' * 64)
        self.assertEqual(event.metadata['reason'], 'invalid_pin_or_policy')
        self.assertEqual(event.metadata['count'], 3)
        serialized_metadata = json.dumps(event.metadata).lower()
        self.assertNotIn('1234', serialized_metadata)
        self.assertNotIn('token secret', serialized_metadata)

    def test_bridge_denial_does_not_poison_following_pin_failure(self):
        bridge_id = '22222222-2222-4222-8222-222222222222'
        pin_id = '33333333-3333-4333-8333-333333333333'
        response = self.signed_post(
            {
                'events': [
                    self.event(
                        id=bridge_id,
                        eventType='LOCAL_LEGACY_POS_BRIDGE_DENIED',
                        terminalId='',
                        reason='terminal_credential_invalid',
                    ),
                    self.event(id=pin_id),
                ]
            }
        )

        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data['acceptedIds'], [bridge_id, pin_id])
        events = {
            event.event_type: event
            for event in SecurityEvent.objects.filter(request_id__in=[
                f'la:{self.device.pk}:{bridge_id}',
                f'la:{self.device.pk}:{pin_id}',
            ])
        }
        self.assertEqual(set(events), {'LOCAL_LEGACY_POS_BRIDGE_DENIED', 'LOCAL_PIN_FAILED'})
        self.assertEqual(events['LOCAL_LEGACY_POS_BRIDGE_DENIED'].severity, SecurityEvent.Severity.HIGH)
        self.assertEqual(events['LOCAL_PIN_FAILED'].severity, SecurityEvent.Severity.MEDIUM)
        for event in events.values():
            self.assertEqual(event.restaurant, self.restaurant)
            self.assertEqual(event.device, self.device)

    def test_legacy_bearer_cannot_upload_security_events(self):
        response = self.client.post(
            self.path,
            {'events': [self.event()]},
            format='json',
            HTTP_AUTHORIZATION='Bearer cpa_legacy-audit-token',
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['code'], 'device_required')
        self.assertFalse(SecurityEvent.objects.exists())

    def test_secret_or_unknown_fields_are_rejected_instead_of_stored(self):
        response = self.signed_post({'events': [self.event(pin='1234', authorization='Token secret')]})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SecurityEvent.objects.exists())

    def test_device_type_and_server_side_tenant_binding_cannot_be_spoofed(self):
        foreign = Restaurant.objects.create(name='Foreign restaurant')
        response = self.signed_post(
            {
                'events': [
                    self.event(
                        restaurantId=str(foreign.pk),
                        deviceId='22222222-2222-4222-8222-222222222222',
                    )
                ]
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SecurityEvent.objects.exists())

    @patch('apps.local_agents.security_events.LOCAL_EVENT_BATCHES_PER_MINUTE', 1)
    def test_verified_device_has_a_dedicated_batch_rate_limit(self):
        first = self.signed_post({'events': [self.event()]})
        second = self.signed_post({'events': [self.event(id='22222222-2222-4222-8222-222222222222')]})

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second['Retry-After'], '60')

    def test_oversized_body_is_rejected_before_device_authentication(self):
        response = self.client.generic(
            'POST',
            self.path,
            b'{}',
            content_type='application/json',
            HTTP_CONTENT_LENGTH=str(128 * 1024 + 1),
        )

        self.assertEqual(response.status_code, 413)
