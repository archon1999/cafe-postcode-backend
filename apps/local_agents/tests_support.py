"""Paired-device fixtures for Agent HTTP/WebSocket contract tests."""
import base64
import hashlib
import os
import time
from datetime import timedelta
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.utils import timezone

from apps.devices.crypto import device_request_message, sha256_hex
from apps.devices.models import Device


def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


class AgentTestIdentity:
    def __init__(self, agent):
        self.private = ed25519.Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.device = Device.objects.create(
            restaurant=agent.restaurant, type=Device.Type.LOCAL_AGENT, name='Signed test Agent',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519, public_key=b64url(public),
            public_key_fingerprint=hashlib.sha256(public).hexdigest(), paired_at=timezone.now(),
            lease_expires_at=timezone.now() + timedelta(days=1),
        )
        agent.device = self.device
        agent.save(update_fields=['device', 'updated_at'])

    def headers(self, method, target, body=b''):
        timestamp, nonce, digest = int(time.time()), b64url(os.urandom(24)), sha256_hex(body)
        message = device_request_message(method=method, request_target=target, device_id=self.device.pk,
            timestamp=timestamp, nonce=nonce, body_sha256=digest)
        return {'x-device-id': str(self.device.pk), 'x-device-timestamp': str(timestamp),
            'x-device-nonce': nonce, 'x-device-content-sha256': digest,
            'x-device-signature': b64url(self.private.sign(message.encode()))}

    def websocket_headers(self, target='/ws/local-agent/'):
        return [(b'origin', b'http://testserver'), *[(k.encode(), v.encode()) for k, v in self.headers('GET', target).items()]]


def bind_agent_client(client, agent, token):
    identity = AgentTestIdentity(agent)
    original = client.generic

    def generic(method, path, data='', content_type='application/octet-stream', secure=False, **extra):
        if path.startswith('/api/v1/local-agent/') and extra.get('HTTP_AUTHORIZATION') == f'Bearer {token}':
            body = data.encode() if isinstance(data, str) else data
            parsed = urlsplit(path)
            target = parsed.path + ('?' + parsed.query if parsed.query else '')
            proof = identity.headers(method, target, body)
            extra.update({'HTTP_' + key.upper().replace('-', '_'): value for key, value in proof.items()})
        return original(method, path, data=data, content_type=content_type, secure=secure, **extra)

    client.generic = generic
    return identity
