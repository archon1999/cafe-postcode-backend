import uuid
from datetime import timedelta

from django.utils import timezone

from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox
from apps.local_agents.mutation_historical_user import archived_historical_pos_user
from apps.local_agents.mutation_inbox import _hash
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.devices.models import Device
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models.employee_profile import EmployeeProfile


class ArchivedHistoricalUserTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.device_id = str(uuid.uuid4())
        self.epoch = 'original-local-agent-epoch'
        self.occurred_at = timezone.now() - timedelta(days=2)
        self.archived_at = timezone.now() - timedelta(days=1)
        self.user.is_active = False
        self.user.save(update_fields=['is_active', 'updated_at'])
        EmployeeProfile.objects.update_or_create(
            user=self.user,
            defaults={'employment_status': EmployeeProfile.EmploymentStatus.ARCHIVED},
        )
        type(self.user).objects.filter(pk=self.user.pk).update(
            created_at=self.occurred_at - timedelta(days=1),
            updated_at=self.archived_at,
        )
        EmployeeProfile.objects.filter(user=self.user).update(updated_at=self.archived_at)

    def operation(self, *, sequence=1, epoch=None, device_id=None, occurred_at=None, version=2):
        return {
            'operationId': 'pos:' + str(uuid.uuid4()),
            'userId': str(self.user.pk),
            'deviceId': device_id or self.device_id,
            'method': 'POST',
            'path': '/api/v1/pos/sales/orders/',
            'body': {'id': str(uuid.uuid4()), 'channel': 'takeaway'},
            'occurredAt': (occurred_at or self.occurred_at).isoformat(),
            'eventVersion': version,
            'ownerEpoch': self.epoch if epoch is None else epoch,
            'sequence': sequence,
        }

    def record(self, op, *, before_archive=False):
        inbox = LocalAgentMutationInbox.objects.create(
            restaurant=self.restaurant,
            operation_id=op['operationId'],
            payload_hash=_hash(op),
            operation=op,
            event_version=op['eventVersion'],
            owner_epoch=op['ownerEpoch'],
            sequence=op['sequence'],
            occurred_at=self.occurred_at,
        )
        if before_archive:
            LocalAgentMutationInbox.objects.filter(pk=inbox.pk).update(
                created_at=self.archived_at - timedelta(hours=1),
            )

    def allowed(self, op):
        return archived_historical_pos_user(
            agent=self.agent, operation=op, user_id=str(self.user.pk),
            device_id=op['deviceId'], occurred_at=timezone.datetime.fromisoformat(op['occurredAt']),
        )

    def test_previously_received_legacy_event_is_admitted_without_reactivating_user(self):
        op = self.operation(version=1)
        self.record(op, before_archive=True)
        self.assertEqual(self.allowed(op).pk, self.user.pk)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_new_event_requires_matching_prearchive_epoch_user_and_device(self):
        old = self.operation()
        self.record(old, before_archive=True)
        new = self.operation(sequence=2)
        self.record(new)
        self.assertEqual(self.allowed(new).pk, self.user.pk)
        for changed in (
            self.operation(sequence=3, epoch='new-epoch'),
            self.operation(sequence=4, device_id=str(uuid.uuid4())),
            self.operation(sequence=5, occurred_at=self.archived_at + timedelta(seconds=1)),
            self.operation(sequence=6, version=1),
        ):
            self.record(changed)
            self.assertIsNone(self.allowed(changed))

    def test_rejects_changed_payload_and_event_without_prearchive_evidence(self):
        op = self.operation()
        self.record(op, before_archive=True)
        changed = {**op, 'body': {'id': str(uuid.uuid4())}}
        self.assertIsNone(self.allowed(changed))
        new = self.operation(sequence=2)
        self.record(new)
        # A new epoch cannot borrow proof from the current one.
        self.assertIsNone(self.allowed(self.operation(sequence=3, epoch='other')))

    def test_processor_projects_recorded_event_without_reactivating_login(self):
        device = Device.objects.create(
            restaurant=self.restaurant, type=Device.Type.POS_TERMINAL,
            name='Original POS', status=Device.Status.ACTIVE,
            paired_at=timezone.now(),
            lease_expires_at=timezone.now() + timedelta(days=1),
        )
        self.device_id = str(device.pk)
        op = self.operation(version=1)
        self.record(op, before_archive=True)
        result = LocalAgentMutationProcessor().process(agent=self.agent, operation=op)
        self.assertTrue(result['applied'], result)
        self.assertTrue(Order.objects.filter(pk=op['body']['id'], opened_by=self.user).exists())
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        after_archive = self.operation(
            sequence=2, occurred_at=self.archived_at + timedelta(seconds=1),
        )
        result = LocalAgentMutationProcessor().process(agent=self.agent, operation=after_archive)
        self.assertEqual(result['code'], 'POS_USER_INVALID')
