import os
import threading

from django.db import close_old_connections
from django.core.cache import cache
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.devices.crypto import pairing_key_proof_message
from apps.devices.models import Device, DevicePairing
from apps.devices.services import DevicePairingError, approve_pairing, create_pairing
from apps.devices.tests.test_device_platform import TestKey, b64url
from apps.restaurants.models import Restaurant
from apps.users.models import User


class DevicePairingConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        cache.clear()

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_claim_creates_exactly_one_device(self):
        restaurant = Restaurant.objects.create(name='Concurrent pairing restaurant')
        superuser = User.objects.create_superuser(
            username='concurrent-device-admin',
            password='Concurrent-Device-Admin-123!',
            full_name='Concurrent Device Admin',
        )
        key = TestKey()
        nonce = b64url(os.urandom(32))
        pairing, _poll_token, claim_token, _claim_url = create_pairing(
            device_type=Device.Type.POS_TERMINAL,
            name='Concurrent POS',
            platform='test',
            app_version='1.0',
            public_key_algorithm=key.algorithm,
            public_key=key.public_key,
            proof_nonce=nonce,
            proof_signature=key.sign(pairing_key_proof_message(nonce=nonce, fingerprint=key.fingerprint)),
        )
        barrier = threading.Barrier(2)
        outcomes = []

        def claim():
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                device = approve_pairing(
                    pairing_id=pairing.pk,
                    claim_token=claim_token,
                    restaurant=restaurant,
                    approved_by=superuser,
                )
                outcomes.append(('success', str(device.pk)))
            except DevicePairingError as error:
                outcomes.append(('rejected', error.code))
            finally:
                close_old_connections()

        first = threading.Thread(target=claim)
        second = threading.Thread(target=claim)
        first.start()
        second.start()
        first.join(timeout=15)
        second.join(timeout=15)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(sum(1 for outcome, _ in outcomes if outcome == 'success'), 1)
        self.assertEqual(sum(1 for outcome, _ in outcomes if outcome == 'rejected'), 1)
        self.assertEqual(Device.objects.filter(type=Device.Type.POS_TERMINAL).count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_pairing_create_allows_one_pending_request_per_key(self):
        key = TestKey()
        proofs = []
        for _ in range(2):
            nonce = b64url(os.urandom(32))
            proofs.append(
                (
                    nonce,
                    key.sign(pairing_key_proof_message(nonce=nonce, fingerprint=key.fingerprint)),
                )
            )
        barrier = threading.Barrier(2)
        outcomes = []

        def create(proof):
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                pairing, _poll_token, _claim_token, _claim_url = create_pairing(
                    device_type=Device.Type.POS_TERMINAL,
                    name='Concurrent POS create',
                    platform='test',
                    app_version='1.0',
                    public_key_algorithm=key.algorithm,
                    public_key=key.public_key,
                    proof_nonce=proof[0],
                    proof_signature=proof[1],
                )
                outcomes.append(('success', str(pairing.pk)))
            except DevicePairingError as error:
                outcomes.append(('rejected', error.code))
            finally:
                close_old_connections()

        first = threading.Thread(target=create, args=(proofs[0],))
        second = threading.Thread(target=create, args=(proofs[1],))
        first.start()
        second.start()
        first.join(timeout=15)
        second.join(timeout=15)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(sum(1 for outcome, _ in outcomes if outcome == 'success'), 1)
        self.assertEqual(sum(1 for outcome, _ in outcomes if outcome == 'rejected'), 1)
        self.assertEqual(outcomes.count(('rejected', 'pairing_conflict')), 1)
        self.assertEqual(
            DevicePairing.objects.filter(
                public_key_fingerprint=key.fingerprint,
                status=DevicePairing.Status.PENDING,
            ).count(),
            1,
        )
