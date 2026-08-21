import base64
import hashlib
import json
import os
import time
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.devices.crypto import (
    device_request_message,
    pairing_key_proof_message,
    pairing_status_message,
    pos_migration_attestation_message,
    sha256_hex,
)
from apps.devices.models import Device, DevicePairing, SecurityEvent, hash_device_secret
from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.services import LocalAgentCommandError, LocalAgentUnavailableError
from apps.kitchen.models import TvMonitorDevice
from apps.kitchen.models.tv_monitor import hash_tv_monitor_secret
from apps.restaurants.models import Restaurant
from apps.sales.tests.support.pos_api import PosTestDataMixin
from apps.users.models import AuthSession, Permission, User
from apps.users.services import AdminAuthService, AuthSessionService


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


class TestKey:
    def __init__(self, algorithm='P256_SHA256'):
        self.algorithm = algorithm
        if algorithm == Device.PublicKeyAlgorithm.ED25519:
            self.private = ed25519.Ed25519PrivateKey.generate()
            raw_public = self.private.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
        else:
            self.private = ec.generate_private_key(ec.SECP256R1())
            raw_public = self.private.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        self.public_key = b64url(raw_public)
        self.fingerprint = hashlib.sha256(raw_public).hexdigest()

    def sign(self, message: str) -> str:
        payload = message.encode('utf-8')
        if self.algorithm == Device.PublicKeyAlgorithm.ED25519:
            return b64url(self.private.sign(payload))
        der_signature = self.private.sign(payload, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der_signature)
        return b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))


@override_settings(
    DEVICE_POS_PROOF_REQUIRED=True,
    DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED=True,
    DEVICE_LEGACY_POS_MIGRATION_ENABLED=True,
    DEVICE_LEGACY_TV_PAIRING_ENABLED=True,
    DEVICE_LEGACY_TV_MIGRATION_ENABLED=True,
)
class DevicePlatformApiTests(PosTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user.set_pin('1111')
        cls.user.save(update_fields=['pin_code'])
        admin_permission, _ = Permission.objects.get_or_create(
            code='catalog_items.view',
            defaults={'name': 'Catalog items view', 'description': 'Catalog admin access'},
        )
        cls.role.permissions.add(admin_permission)
        cls.tariff.permissions.add(admin_permission)
        cls.superuser = User.objects.create_superuser(
            username='device-control-admin',
            password='Strong-Device-Control-123!',
            full_name='Device Control Admin',
        )
        cls.other_restaurant = Restaurant.objects.create(name='Other tenant')

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client.force_authenticate(user=None)
        self.client.credentials()

    def authenticate_superuser(self, *, recent=True):
        verified_at = timezone.now() - timedelta(minutes=16) if not recent else timezone.now()
        request = APIRequestFactory().post(
            '/',
            HTTP_ORIGIN='https://admin.cafe-postcode.uz',
            REMOTE_ADDR='192.0.2.44',
        )
        bundle = AdminAuthService().issue_credentials(
            user=self.superuser,
            request=request,
            mfa_verified_at=verified_at,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {bundle.access_token}')
        return bundle

    @staticmethod
    def key_proof(key):
        nonce = b64url(os.urandom(32))
        return {
            'nonce': nonce,
            'signature': key.sign(pairing_key_proof_message(nonce=nonce, fingerprint=key.fingerprint)),
        }

    def legacy_pos_migration_payload(self, *, terminal_id='legacy-terminal-0001'):
        agent_key = TestKey(Device.PublicKeyAlgorithm.ED25519)
        now = timezone.now()
        agent_device = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.LOCAL_AGENT,
            name='Paired agent',
            public_key_algorithm=agent_key.algorithm,
            public_key=agent_key.public_key,
            public_key_fingerprint=agent_key.fingerprint,
            capabilities=['local_agent'],
            paired_at=now,
            lease_expires_at=now + timedelta(hours=24),
        )
        agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Paired agent')
        agent.device = agent_device
        agent.credential_migrated_at = now
        agent.save(update_fields=['device', 'credential_migrated_at', 'updated_at'])
        pos_key = TestKey()
        attestation = {
            'version': 'v1',
            'restaurant_id': self.restaurant.pk,
            'local_agent_device_id': agent_device.pk,
            'terminal_id': terminal_id,
            'public_key_fingerprint': pos_key.fingerprint,
            'issued_at': int(time.time()),
            'expires_at': int(time.time()) + 300,
            'nonce': b64url(os.urandom(32)),
        }
        attestation['signature'] = agent_key.sign(pos_migration_attestation_message(attestation))
        payload = {
            'name': 'Migrated POS',
            'platform': 'browser',
            'appVersion': '1.0.0',
            'publicKeyAlgorithm': pos_key.algorithm,
            'publicKey': pos_key.public_key,
            'keyProof': self.key_proof(pos_key),
            'agentAttestation': {
                'version': attestation['version'],
                'restaurantId': str(attestation['restaurant_id']),
                'localAgentDeviceId': str(attestation['local_agent_device_id']),
                'terminalId': attestation['terminal_id'],
                'publicKeyFingerprint': attestation['public_key_fingerprint'],
                'issuedAt': attestation['issued_at'],
                'expiresAt': attestation['expires_at'],
                'nonce': attestation['nonce'],
                'signature': attestation['signature'],
            },
        }
        return agent_device, agent_key, pos_key, payload

    def create_pairing(self, *, key=None, device_type=Device.Type.POS_TERMINAL, name='Main POS'):
        key = key or TestKey()
        response = self.client.post(
            '/api/v1/devices/pairings/',
            {
                'deviceType': device_type,
                'name': name,
                'platform': 'test',
                'appVersion': '1.0.0',
                'publicKeyAlgorithm': key.algorithm,
                'publicKey': key.public_key,
                'keyProof': self.key_proof(key),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return key, response.json()

    def approve_pairing(self, pairing, *, restaurant=None, name=''):
        self.authenticate_superuser()
        payload = {
            'claimToken': pairing['claimToken'],
            'restaurantId': str((restaurant or self.restaurant).pk),
        }
        if name:
            payload['name'] = name
        response = self.client.post(
            f"/api/v1/admin/devices/pairings/{pairing['id']}/approve/",
            payload,
            format='json',
        )
        self.client.credentials()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return Device.objects.get(pk=response.json()['device']['id'])

    def status_pairing(self, pairing, key, *, private_key=None):
        timestamp = int(time.time())
        nonce = b64url(os.urandom(32))
        signer = private_key or key
        signature = signer.sign(
            pairing_status_message(
                pairing_id=pairing['id'],
                timestamp=timestamp,
                nonce=nonce,
                poll_token=pairing['pollToken'],
            )
        )
        return self.client.post(
            f"/api/v1/devices/pairings/{pairing['id']}/status/",
            {
                'pollToken': pairing['pollToken'],
                'timestamp': timestamp,
                'nonce': nonce,
                'signature': signature,
            },
            format='json',
        )

    def signed_request(self, method, path, *, key, device, payload=None, token=None, proof=None):
        body = b'' if payload is None else json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if proof is None:
            timestamp = int(time.time())
            nonce = b64url(os.urandom(32))
            body_hash = sha256_hex(body)
            signature = key.sign(
                device_request_message(
                    method=method,
                    request_target=path,
                    device_id=device.pk,
                    timestamp=timestamp,
                    nonce=nonce,
                    body_sha256=body_hash,
                )
            )
            proof = {
                'HTTP_X_DEVICE_ID': str(device.pk),
                'HTTP_X_DEVICE_TIMESTAMP': str(timestamp),
                'HTTP_X_DEVICE_NONCE': nonce,
                'HTTP_X_DEVICE_CONTENT_SHA256': body_hash,
                'HTTP_X_DEVICE_SIGNATURE': signature,
            }
        headers = dict(proof)
        if token:
            headers['HTTP_AUTHORIZATION'] = f'Token {token}'
        response = self.client.generic(
            method,
            path,
            data=body,
            content_type='application/json',
            **headers,
        )
        return response, proof

    def pair_device(self, *, device_type=Device.Type.POS_TERMINAL, restaurant=None, algorithm='P256_SHA256'):
        key = TestKey(algorithm)
        _, pairing = self.create_pairing(key=key, device_type=device_type)
        device = self.approve_pairing(pairing, restaurant=restaurant)
        return key, pairing, device

    def test_pairing_proves_key_possession_hides_raw_secrets_and_is_single_decision(self):
        key, pairing = self.create_pairing()
        stored = DevicePairing.objects.get(pk=pairing['id'])
        self.assertNotEqual(stored.poll_token_hash, pairing['pollToken'])
        self.assertNotEqual(stored.claim_token_hash, pairing['claimToken'])
        self.assertAlmostEqual((stored.expires_at - stored.created_at).total_seconds(), 600, delta=1)
        self.assertEqual(stored.poll_token_hash, hash_device_secret(pairing['pollToken']))
        self.assertNotIn(pairing['pollToken'], json.dumps(pairing.get('claimUrl', '')))
        claim_url = urlsplit(pairing['claimUrl'])
        self.assertEqual(claim_url.scheme, 'https')
        self.assertEqual(claim_url.netloc, 'control.cafe-postcode.uz')
        self.assertEqual(claim_url.path, '/control/pair')
        self.assertEqual(claim_url.query, '')
        expected_fragment = urlencode(
            {
                'v': 1,
                'pairingId': pairing['id'],
                'claimToken': pairing['claimToken'],
            }
        )
        self.assertEqual(
            pairing['claimUrl'],
            f'https://control.cafe-postcode.uz/control/pair#{expected_fragment}',
        )
        self.assertNotIn(pairing['claimToken'], claim_url.query)
        self.assertGreater(pairing['qrSize'], 20)
        self.assertTrue(pairing['qrPath'].startswith('M'))
        self.assertNotIn(pairing['claimToken'], pairing['qrPath'])
        fragment = parse_qs(claim_url.fragment)
        self.assertEqual(fragment['v'], ['1'])
        self.assertEqual(fragment['pairingId'], [pairing['id']])
        self.assertEqual(fragment['claimToken'], [pairing['claimToken']])

        wrong_key = TestKey()
        copied_response = self.status_pairing(pairing, key, private_key=wrong_key)
        self.assertEqual(copied_response.status_code, status.HTTP_400_BAD_REQUEST)
        pending_response = self.status_pairing(pairing, key)
        self.assertEqual(pending_response.status_code, status.HTTP_200_OK)
        self.assertEqual(pending_response.json()['status'], 'pending')

        device = self.approve_pairing(pairing)
        paired_response = self.status_pairing(pairing, key)
        self.assertEqual(paired_response.status_code, status.HTTP_200_OK)
        self.assertEqual(paired_response.json()['status'], 'paired')
        self.assertEqual(paired_response.json()['device']['id'], str(device.pk))

        self.authenticate_superuser()
        replayed_claim = self.client.post(
            f"/api/v1/admin/devices/pairings/{pairing['id']}/approve/",
            {'claimToken': pairing['claimToken'], 'restaurantId': str(self.restaurant.pk)},
            format='json',
        )
        self.assertEqual(replayed_claim.status_code, status.HTTP_409_CONFLICT)

    def test_pairing_create_rejects_proof_replay_and_duplicate_live_key(self):
        key = TestKey()
        payload = {
            'deviceType': Device.Type.POS_TERMINAL,
            'name': 'Replay-safe POS',
            'platform': 'test',
            'appVersion': '1.0.0',
            'publicKeyAlgorithm': key.algorithm,
            'publicKey': key.public_key,
            'keyProof': self.key_proof(key),
        }
        created = self.client.post('/api/v1/devices/pairings/', payload, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)

        replay = self.client.post('/api/v1/devices/pairings/', payload, format='json')
        self.assertEqual(replay.status_code, status.HTTP_409_CONFLICT, replay.data)
        self.assertEqual(replay.json()['code'], 'pairing_replay')
        self.assertEqual(DevicePairing.objects.filter(public_key_fingerprint=key.fingerprint).count(), 1)
        self.assertTrue(SecurityEvent.objects.filter(event_type='DEVICE_PAIRING_REPLAY_DETECTED').exists())

        payload['keyProof'] = self.key_proof(key)
        duplicate = self.client.post('/api/v1/devices/pairings/', payload, format='json')
        self.assertEqual(duplicate.status_code, status.HTTP_409_CONFLICT, duplicate.data)
        self.assertEqual(duplicate.json()['code'], 'pairing_conflict')

        first = DevicePairing.objects.get(pk=created.json()['id'])
        DevicePairing.objects.filter(pk=first.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        payload['keyProof'] = self.key_proof(key)
        replacement = self.client.post('/api/v1/devices/pairings/', payload, format='json')
        self.assertEqual(replacement.status_code, status.HTTP_201_CREATED, replacement.data)
        first.refresh_from_db()
        self.assertEqual(first.status, DevicePairing.Status.EXPIRED)

    def test_pairing_create_has_a_dedicated_public_rate_limit(self):
        for index in range(6):
            self.create_pairing(name=f'Rate-limited POS {index}')

        key = TestKey()
        throttled = self.client.post(
            '/api/v1/devices/pairings/',
            {
                'deviceType': Device.Type.POS_TERMINAL,
                'name': 'One request too many',
                'platform': 'test',
                'appVersion': '1.0.0',
                'publicKeyAlgorithm': key.algorithm,
                'publicKey': key.public_key,
                'keyProof': self.key_proof(key),
            },
            format='json',
        )
        self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS, throttled.data)
        self.assertEqual(DevicePairing.objects.count(), 6)

    def test_tv_pairing_fresh_proof_replaces_inaccessible_pending_request(self):
        key = TestKey()
        payload = {
            'deviceType': Device.Type.TV_MONITOR,
            'name': 'Kitchen TV',
            'platform': 'Linux armv7l',
            'appVersion': 'web',
            'publicKeyAlgorithm': key.algorithm,
            'publicKey': key.public_key,
            'keyProof': self.key_proof(key),
        }
        first = self.client.post('/api/v1/devices/pairings/', payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)

        payload['keyProof'] = self.key_proof(key)
        replacement = self.client.post('/api/v1/devices/pairings/', payload, format='json')
        self.assertEqual(replacement.status_code, status.HTTP_201_CREATED, replacement.data)
        self.assertNotEqual(replacement.json()['id'], first.json()['id'])

        first_row = DevicePairing.objects.get(pk=first.json()['id'])
        self.assertEqual(first_row.status, DevicePairing.Status.EXPIRED)
        self.assertEqual(
            DevicePairing.objects.filter(
                public_key_fingerprint=key.fingerprint,
                status=DevicePairing.Status.PENDING,
            ).count(),
            1,
        )

    def test_pos_session_is_device_bound_replay_safe_lockable_and_revocable(self):
        key, _pairing, device = self.pair_device()
        login, _ = self.signed_request(
            'POST',
            '/api/v1/pos/auth/pin-login/',
            key=key,
            device=device,
            payload={'pin': '1111'},
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK, login.data)
        token = login.json()['token']
        session = AuthSession.objects.get(token_key_hash=AuthSession.build_token_key_hash(token))
        self.assertEqual(session.device, device)
        self.assertEqual(session.restaurant, self.restaurant)

        me, proof = self.signed_request(
            'GET', '/api/v1/pos/auth/me/', key=key, device=device, token=token
        )
        self.assertEqual(me.status_code, status.HTTP_200_OK, me.data)
        replay, _ = self.signed_request(
            'GET', '/api/v1/pos/auth/me/', key=key, device=device, token=token, proof=proof
        )
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(replay.json()['code'], 'device_replay_detected')

        locked, _ = self.signed_request(
            'POST', '/api/v1/pos/auth/lock/', key=key, device=device, token=token, payload={}
        )
        self.assertEqual(locked.status_code, status.HTTP_204_NO_CONTENT, locked.data)
        blocked, _ = self.signed_request(
            'GET', '/api/v1/pos/auth/me/', key=key, device=device, token=token
        )
        self.assertEqual(blocked.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(blocked.json()['code'], 'session_locked')

        confirmed_lock, _ = self.signed_request(
            'POST', '/api/v1/pos/auth/lock/', key=key, device=device, token=token, payload={}
        )
        self.assertEqual(confirmed_lock.status_code, status.HTTP_204_NO_CONTENT, confirmed_lock.data)

        wrong_pin, _ = self.signed_request(
            'POST', '/api/v1/pos/auth/unlock/', key=key, device=device, token=token, payload={'pin': '9999'}
        )
        self.assertEqual(wrong_pin.status_code, status.HTTP_400_BAD_REQUEST)
        unlocked, _ = self.signed_request(
            'POST', '/api/v1/pos/auth/unlock/', key=key, device=device, token=token, payload={'pin': '1111'}
        )
        self.assertEqual(unlocked.status_code, status.HTTP_200_OK, unlocked.data)
        new_token = unlocked.json()['token']
        self.assertNotEqual(new_token, token)
        session.refresh_from_db()
        self.assertEqual(session.status, AuthSession.Status.REVOKED)

        LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')
        self.authenticate_superuser()
        with self.captureOnCommitCallbacks(execute=True):
            revoked = self.client.post(
                f'/api/v1/admin/devices/{device.pk}/revoke/',
                {'reason': 'Terminal was retired'},
                format='json',
            )
        self.client.credentials()
        self.assertEqual(revoked.status_code, status.HTTP_200_OK, revoked.data)
        revoked_me, _ = self.signed_request('GET', '/api/v1/devices/me/', key=key, device=device)
        self.assertEqual(revoked_me.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(revoked_me.json()['code'], 'device_revoked')
        revoked_renew, _ = self.signed_request(
            'POST', '/api/v1/devices/lease/renew/', key=key, device=device, payload={}
        )
        self.assertEqual(revoked_renew.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(revoked_renew.json()['code'], 'device_revoked')
        self.assertTrue(SecurityEvent.objects.filter(event_type='PIN_FAILED', device=device).exists())
        self.assertTrue(SecurityEvent.objects.filter(event_type='DEVICE_REVOKED', device=device).exists())
        revoke_command = LocalAgentCommand.objects.get(command_type='edge.terminal.revoke')
        self.assertEqual(revoke_command.payload, {'backendDeviceId': str(device.id)})

    def test_active_lease_renews_and_expired_active_device_recovers_with_same_key(self):
        key, _pairing, device = self.pair_device()
        renewed, proof = self.signed_request(
            'POST', '/api/v1/devices/lease/renew/', key=key, device=device, payload={}
        )
        self.assertEqual(renewed.status_code, status.HTTP_200_OK, renewed.data)
        replay, _ = self.signed_request(
            'POST', '/api/v1/devices/lease/renew/', key=key, device=device, payload={}, proof=proof
        )
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(replay.json()['code'], 'device_replay_detected')

        Device.objects.filter(pk=device.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        device.refresh_from_db()
        expired, _ = self.signed_request('GET', '/api/v1/devices/me/', key=key, device=device)
        self.assertEqual(expired.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(expired.json()['code'], 'device_lease_expired')

        recovered, _ = self.signed_request(
            'POST', '/api/v1/devices/lease/renew/', key=key, device=device, payload={}
        )
        self.assertEqual(recovered.status_code, status.HTTP_200_OK, recovered.data)
        device.refresh_from_db()
        self.assertGreater(device.lease_expires_at, timezone.now())
        self.assertTrue(
            SecurityEvent.objects.filter(event_type='DEVICE_LEASE_RECOVERED', device=device).exists()
        )

        recovered_me, _ = self.signed_request('GET', '/api/v1/devices/me/', key=key, device=device)
        self.assertEqual(recovered_me.status_code, status.HTTP_200_OK, recovered_me.data)

    @patch('apps.users.api.pos.views.auth.LocalAgentCommandService.execute')
    def test_restaurant_code_endpoint_is_context_only_and_rejects_invalid_code(self, execute):
        response = self.client.post(
            '/api/v1/pos/auth/restaurant-code/',
            {'code': 'LEGACY'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.json()['code'], 'restaurant_code_invalid')
        self.assertNotIn('token', response.json())
        self.assertNotIn('edgeToken', response.json())
        execute.assert_not_called()

    def test_proof_cutover_revokes_pre_migration_unbound_pos_session(self):
        request = APIRequestFactory().post('/test', REMOTE_ADDR='192.0.2.10')
        token, session = AuthSessionService().issue(
            user=self.user,
            request=request,
            surface=AuthSession.Surface.POS,
            restaurant=self.restaurant,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        response = self.client.get('/api/v1/pos/auth/me/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['code'], 'device_proof_required')
        session.refresh_from_db()
        self.assertEqual(session.status, AuthSession.Status.REVOKED)
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type='LEGACY_POS_SESSION_REJECTED',
                auth_session_id=session.pk,
            ).exists()
        )

    def test_device_type_and_restaurant_are_enforced_independently_of_user_token(self):
        tv_key, _pairing, tv_device = self.pair_device(device_type=Device.Type.TV_MONITOR)
        wrong_surface, _ = self.signed_request(
            'POST',
            '/api/v1/pos/auth/pin-login/',
            key=tv_key,
            device=tv_device,
            payload={'pin': '1111'},
        )
        self.assertEqual(wrong_surface.status_code, status.HTTP_401_UNAUTHORIZED)

        foreign_key, _pairing, foreign_device = self.pair_device(restaurant=self.other_restaurant)
        request = APIRequestFactory().post('/test', REMOTE_ADDR='192.0.2.10')
        token, _session = AuthSessionService().issue(
            user=self.user,
            request=request,
            surface=AuthSession.Surface.POS,
            device=foreign_device,
            restaurant=self.restaurant,
        )
        mismatch, _ = self.signed_request(
            'GET',
            '/api/v1/pos/auth/me/',
            key=foreign_key,
            device=foreign_device,
            token=token,
        )
        self.assertEqual(mismatch.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(mismatch.json()['code'], 'device_restaurant_mismatch')

    @override_settings(DEVICE_LEGACY_TV_PAIRING_ENABLED=False, DEVICE_LEGACY_TV_MIGRATION_ENABLED=True)
    def test_legacy_tv_token_migrates_once_and_is_immediately_retired(self):
        legacy_pairing = self.client.post('/api/v1/pos/monitor/tv-pairings/', {}, format='json')
        self.assertEqual(legacy_pairing.status_code, status.HTTP_410_GONE)

        raw_token = 'legacy-tv-token-with-sufficient-entropy'
        legacy_tv = TvMonitorDevice.objects.create(
            restaurant=self.restaurant,
            token_hash=hash_tv_monitor_secret(raw_token),
            paired_at=timezone.now(),
        )
        key = TestKey()
        payload = {
            'name': 'Kitchen TV',
            'platform': 'web',
            'appVersion': '2.0.0',
            'publicKeyAlgorithm': key.algorithm,
            'publicKey': key.public_key,
            'keyProof': self.key_proof(key),
        }

        migrated = self.client.post(
            '/api/v1/devices/legacy-tv-migration/',
            payload,
            format='json',
            HTTP_X_TV_TOKEN=raw_token,
        )

        self.assertEqual(migrated.status_code, status.HTTP_201_CREATED, migrated.data)
        legacy_tv.refresh_from_db()
        self.assertIsNotNone(legacy_tv.device_id)
        self.assertIsNotNone(legacy_tv.credential_migrated_at)
        device = legacy_tv.device
        self.assertEqual(device.type, Device.Type.TV_MONITOR)
        self.assertEqual(device.public_key_fingerprint, key.fingerprint)

        retired = self.client.get(
            '/api/v1/pos/monitor/tv-kitchen-queue/',
            HTTP_X_TV_TOKEN=raw_token,
        )
        self.assertEqual(retired.status_code, status.HTTP_401_UNAUTHORIZED)

        signed, _proof = self.signed_request(
            'GET',
            '/api/v1/pos/monitor/tv-kitchen-queue/',
            key=key,
            device=device,
        )
        self.assertEqual(signed.status_code, status.HTTP_200_OK, signed.data)

        retried = self.client.post(
            '/api/v1/devices/legacy-tv-migration/',
            payload,
            format='json',
            HTTP_X_TV_TOKEN=raw_token,
        )
        self.assertEqual(retried.status_code, status.HTTP_200_OK, retried.data)

    def test_local_agent_legacy_credential_migrates_once_to_ed25519_device(self):
        agent, raw_token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Legacy agent')
        key = TestKey(Device.PublicKeyAlgorithm.ED25519)
        payload = {
            'name': 'Main Local Agent',
            'platform': 'windows',
            'appVersion': '2.0.0',
            'publicKeyAlgorithm': key.algorithm,
            'publicKey': key.public_key,
            'keyProof': self.key_proof(key),
        }
        migrated = self.client.post(
            '/api/v1/local-agent/device-migration/',
            payload,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {raw_token}',
        )
        self.assertEqual(migrated.status_code, status.HTTP_201_CREATED, migrated.data)
        agent.refresh_from_db()
        self.assertIsNotNone(agent.device_id)
        self.assertIsNotNone(agent.credential_migrated_at)
        self.assertEqual(agent.device.public_key_fingerprint, key.fingerprint)
        migrated_device_id = agent.device_id

        bounded_bridge = self.client.get(
            '/api/v1/local-agent/auth/token/',
            HTTP_AUTHORIZATION=f'Bearer {raw_token}',
        )
        self.assertEqual(bounded_bridge.status_code, status.HTTP_200_OK)
        with override_settings(DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=False):
            retired_credential = self.client.get(
                '/api/v1/local-agent/auth/token/',
                HTTP_AUTHORIZATION=f'Bearer {raw_token}',
            )
        self.assertEqual(retired_credential.status_code, status.HTTP_401_UNAUTHORIZED)

        idempotent = self.client.post(
            '/api/v1/local-agent/device-migration/',
            payload,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {raw_token}',
        )
        self.assertEqual(idempotent.status_code, status.HTTP_200_OK, idempotent.data)
        self.assertEqual(Device.objects.filter(type=Device.Type.LOCAL_AGENT).count(), 1)

        replacement_key = TestKey(Device.PublicKeyAlgorithm.ED25519)
        replacement_payload = {
            **payload,
            'name': 'Recovered Local Agent',
            'appVersion': '2.0.1',
            'publicKey': replacement_key.public_key,
            'keyProof': self.key_proof(replacement_key),
        }
        recovered = self.client.post(
            '/api/v1/local-agent/device-migration/',
            replacement_payload,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {raw_token}',
        )
        self.assertEqual(recovered.status_code, status.HTTP_200_OK, recovered.data)
        agent.refresh_from_db()
        agent.device.refresh_from_db()
        device = agent.device
        self.assertEqual(agent.device_id, migrated_device_id)
        self.assertEqual(device.public_key_fingerprint, replacement_key.fingerprint)
        self.assertEqual(device.app_version, '2.0.1')
        self.assertEqual(Device.objects.filter(type=Device.Type.LOCAL_AGENT).count(), 1)

    def test_post_cutover_local_agent_cannot_enter_legacy_migration_cohort(self):
        now = timezone.now()
        agent, raw_token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='New agent')
        key = TestKey(Device.PublicKeyAlgorithm.ED25519)
        payload = {
            'name': 'New Local Agent',
            'publicKeyAlgorithm': key.algorithm,
            'publicKey': key.public_key,
            'keyProof': self.key_proof(key),
        }
        with override_settings(
            DEVICE_LEGACY_MIGRATION_STARTED_AT=(now - timedelta(hours=1)).isoformat(),
            DEVICE_LEGACY_MIGRATION_DEADLINE=(now + timedelta(hours=1)).isoformat(),
        ):
            response = self.client.post(
                '/api/v1/local-agent/device-migration/',
                payload,
                format='json',
                HTTP_AUTHORIZATION=f'Bearer {raw_token}',
            )

        self.assertGreater(agent.created_at, now - timedelta(hours=1))
        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.json()['code'], 'legacy_migration_disabled')

    @patch('apps.devices.views.LegacyPosMigrationView.command_service_class')
    def test_post_cutover_agent_cannot_attest_pairing_free_pos_migration(self, command_service_class):
        now = timezone.now()
        _agent_device, _agent_key, _pos_key, payload = self.legacy_pos_migration_payload(
            terminal_id='post-cutover-terminal'
        )
        with override_settings(
            DEVICE_LEGACY_MIGRATION_STARTED_AT=(now - timedelta(hours=1)).isoformat(),
            DEVICE_LEGACY_MIGRATION_DEADLINE=(now + timedelta(hours=1)).isoformat(),
        ):
            response = self.client.post('/api/v1/devices/legacy-pos-migration/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['code'], 'migration_attestation_invalid')
        command_service_class.return_value.execute.assert_not_called()

    @patch('apps.devices.views.LegacyPosMigrationView.command_service_class')
    def test_agent_attested_pos_migration_needs_no_server_session_and_claims_terminal_once(
        self,
        command_service_class,
    ):
        agent_device, agent_key, pos_key, payload = self.legacy_pos_migration_payload()
        execute = command_service_class.return_value.execute
        execute.side_effect = lambda **kwargs: {
            'terminalId': kwargs['payload']['terminalId'],
            'deviceId': kwargs['payload']['deviceId'],
            'restaurantId': str(kwargs['restaurant'].pk),
        }
        migrated = self.client.post(
            '/api/v1/devices/legacy-pos-migration/',
            payload,
            format='json',
        )
        self.assertEqual(migrated.status_code, status.HTTP_201_CREATED, migrated.data)
        migrated_device = Device.objects.get(pk=migrated.json()['device']['id'])
        self.assertEqual(migrated_device.restaurant, self.restaurant)
        self.assertIsNotNone(migrated_device.legacy_migration_key)
        execute.assert_called_once_with(
            restaurant=self.restaurant,
            command_type='edge.terminal.bind',
            payload={
                'terminalId': 'legacy-terminal-0001',
                'terminalName': 'Migrated POS',
                'deviceId': str(migrated_device.pk),
                'publicKeyAlgorithm': Device.PublicKeyAlgorithm.P256_SHA256,
                'publicKey': pos_key.public_key,
                'publicKeyFingerprint': pos_key.fingerprint,
            },
            timeout_seconds=2,
        )

        idempotent = self.client.post(
            '/api/v1/devices/legacy-pos-migration/',
            payload,
            format='json',
        )
        self.assertEqual(idempotent.status_code, status.HTTP_200_OK, idempotent.data)
        self.assertEqual(idempotent.json()['device']['id'], str(migrated_device.pk))
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args.kwargs['payload']['deviceId'], str(migrated_device.pk))

        other_pos_key = TestKey()
        conflict_attestation = {
            'version': 'v1',
            'restaurant_id': self.restaurant.pk,
            'local_agent_device_id': agent_device.pk,
            'terminal_id': 'legacy-terminal-0001',
            'public_key_fingerprint': other_pos_key.fingerprint,
            'issued_at': int(time.time()),
            'expires_at': int(time.time()) + 300,
            'nonce': b64url(os.urandom(32)),
        }
        conflict_attestation['signature'] = agent_key.sign(
            pos_migration_attestation_message(conflict_attestation)
        )
        conflict_payload = {
            **payload,
            'publicKey': other_pos_key.public_key,
            'keyProof': self.key_proof(other_pos_key),
            'agentAttestation': {
                'version': conflict_attestation['version'],
                'restaurantId': str(conflict_attestation['restaurant_id']),
                'localAgentDeviceId': str(conflict_attestation['local_agent_device_id']),
                'terminalId': conflict_attestation['terminal_id'],
                'publicKeyFingerprint': conflict_attestation['public_key_fingerprint'],
                'issuedAt': conflict_attestation['issued_at'],
                'expiresAt': conflict_attestation['expires_at'],
                'nonce': conflict_attestation['nonce'],
                'signature': conflict_attestation['signature'],
            },
        }
        conflict = self.client.post('/api/v1/devices/legacy-pos-migration/', conflict_payload, format='json')
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT, conflict.data)
        self.assertEqual(conflict.json()['code'], 'terminal_already_migrated')
        self.assertEqual(Device.objects.filter(type=Device.Type.POS_TERMINAL).count(), 1)
        self.assertEqual(execute.call_count, 2)

    @patch('apps.devices.views.LegacyPosMigrationView.command_service_class')
    def test_agent_attested_pos_migration_keeps_device_for_retry_but_returns_503_when_agent_is_unavailable(
        self,
        command_service_class,
    ):
        agent_device, _agent_key, pos_key, payload = self.legacy_pos_migration_payload(
            terminal_id='legacy-terminal-offline'
        )
        command_service_class.return_value.execute.side_effect = LocalAgentUnavailableError('offline')

        migrated = self.client.post('/api/v1/devices/legacy-pos-migration/', payload, format='json')

        self.assertEqual(migrated.status_code, status.HTTP_503_SERVICE_UNAVAILABLE, migrated.data)
        self.assertEqual(migrated.json()['code'], 'local_agent_unavailable')
        device = Device.objects.get(public_key_fingerprint=pos_key.fingerprint)
        self.assertEqual(device.metadata['terminalId'], 'legacy-terminal-offline')
        failure = SecurityEvent.objects.get(event_type='LEGACY_POS_TERMINAL_BIND_FAILED', device=device)
        self.assertEqual(
            failure.metadata,
            {'agentDeviceId': str(agent_device.pk), 'reason': 'agent_unavailable'},
        )

    @patch('apps.devices.views.LegacyPosMigrationView.command_service_class')
    def test_agent_attested_pos_migration_returns_502_without_binding_on_command_failure(
        self,
        command_service_class,
    ):
        _agent_device, _agent_key, pos_key, payload = self.legacy_pos_migration_payload(
            terminal_id='legacy-terminal-failed'
        )
        command_service_class.return_value.execute.side_effect = LocalAgentCommandError('rejected')

        migrated = self.client.post('/api/v1/devices/legacy-pos-migration/', payload, format='json')

        self.assertEqual(migrated.status_code, status.HTTP_502_BAD_GATEWAY, migrated.data)
        self.assertEqual(migrated.json()['code'], 'terminal_bind_failed')
        self.assertTrue(Device.objects.filter(public_key_fingerprint=pos_key.fingerprint).exists())

    @patch('apps.devices.views.LegacyPosMigrationView.command_service_class')
    def test_agent_attested_pos_migration_rejects_mismatched_terminal_binding_ack(
        self,
        command_service_class,
    ):
        _agent_device, _agent_key, pos_key, payload = self.legacy_pos_migration_payload(
            terminal_id='legacy-terminal-mismatch'
        )
        command_service_class.return_value.execute.return_value = {
            'terminalId': 'different-terminal',
            'deviceId': '00000000-0000-4000-8000-000000000000',
            'restaurantId': str(self.restaurant.pk),
        }

        migrated = self.client.post('/api/v1/devices/legacy-pos-migration/', payload, format='json')

        self.assertEqual(migrated.status_code, status.HTTP_502_BAD_GATEWAY, migrated.data)
        self.assertEqual(migrated.json()['code'], 'terminal_bind_failed')
        device = Device.objects.get(public_key_fingerprint=pos_key.fingerprint)
        failure = SecurityEvent.objects.get(event_type='LEGACY_POS_TERMINAL_BIND_FAILED', device=device)
        self.assertEqual(failure.metadata['reason'], 'ack_mismatch')

    def test_admin_lists_use_project_pagination_and_security_events_are_tenant_scoped(self):
        _key, _pairing, device = self.pair_device()
        own_event = SecurityEvent.objects.create(
            event_type='PIN_FAILED',
            severity=SecurityEvent.Severity.MEDIUM,
            restaurant=self.restaurant,
            device=device,
            result='DENIED',
        )
        SecurityEvent.objects.create(
            event_type='PIN_FAILED',
            severity=SecurityEvent.Severity.HIGH,
            restaurant=self.other_restaurant,
            result='DENIED',
        )

        self.authenticate_superuser()
        devices = self.client.get('/api/v1/admin/devices/?deviceType=POS_TERMINAL&page_size=5')
        self.assertEqual(devices.status_code, status.HTTP_200_OK, devices.data)
        self.assertEqual(set(devices.json()), {'page', 'pageSize', 'count', 'total', 'pagesCount', 'data'})
        self.assertEqual(devices.json()['data'][0]['id'], str(device.pk))

        self.client.force_authenticate(self.user)
        events = self.client.get('/api/v1/admin/security-events/?eventType=PIN_FAILED&page_size=10')
        self.assertEqual(events.status_code, status.HTTP_200_OK, events.data)
        self.assertEqual(events.json()['total'], 1)
        self.assertEqual(events.json()['data'][0]['id'], str(own_event.pk))
        acknowledged = self.client.post(
            f'/api/v1/admin/security-events/{own_event.pk}/acknowledge/',
            {},
            format='json',
        )
        self.assertEqual(acknowledged.status_code, status.HTTP_200_OK, acknowledged.data)
        own_event.refresh_from_db()
        self.assertEqual(own_event.acknowledged_by, self.user)

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_sensitive_device_decisions_require_recent_mfa_when_rollback_flag_is_enabled(self):
        self.client.credentials()
        _key, pairing = self.create_pairing()
        self.authenticate_superuser(recent=False)
        stale_approve = self.client.post(
            f"/api/v1/admin/devices/pairings/{pairing['id']}/approve/",
            {'claimToken': pairing['claimToken'], 'restaurantId': str(self.restaurant.pk)},
            format='json',
        )
        self.assertEqual(stale_approve.status_code, status.HTTP_403_FORBIDDEN, stale_approve.data)
        self.assertEqual(stale_approve.json()['code'], 'mfa_step_up_required')

        self.authenticate_superuser()
        approved = self.client.post(
            f"/api/v1/admin/devices/pairings/{pairing['id']}/approve/",
            {'claimToken': pairing['claimToken'], 'restaurantId': str(self.restaurant.pk)},
            format='json',
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK, approved.data)
        device = Device.objects.get(pk=approved.json()['device']['id'])

        self.client.credentials()
        _key, reject_pairing = self.create_pairing()
        self.authenticate_superuser(recent=False)
        stale_reject = self.client.post(
            f"/api/v1/admin/devices/pairings/{reject_pairing['id']}/reject/",
            {'claimToken': reject_pairing['claimToken']},
            format='json',
        )
        self.assertEqual(stale_reject.status_code, status.HTTP_403_FORBIDDEN, stale_reject.data)
        self.assertEqual(stale_reject.json()['code'], 'mfa_step_up_required')

        self.authenticate_superuser()
        rejected = self.client.post(
            f"/api/v1/admin/devices/pairings/{reject_pairing['id']}/reject/",
            {'claimToken': reject_pairing['claimToken']},
            format='json',
        )
        self.assertEqual(rejected.status_code, status.HTTP_200_OK, rejected.data)

        self.authenticate_superuser(recent=False)
        stale_revoke = self.client.post(
            f'/api/v1/admin/devices/{device.pk}/revoke/',
            {'reason': 'Step-up regression test'},
            format='json',
        )
        self.assertEqual(stale_revoke.status_code, status.HTTP_403_FORBIDDEN, stale_revoke.data)
        self.assertEqual(stale_revoke.json()['code'], 'mfa_step_up_required')
