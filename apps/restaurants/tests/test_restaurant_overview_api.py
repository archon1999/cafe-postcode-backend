from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.catalog.models import CatalogItem
from apps.devices.models import Device
from apps.platform.models import BusinessPartner, RestaurantEntitlement, Tariff
from apps.restaurants.models import (
    CashDesk,
    DistributionPoint,
    PrepStation,
    Restaurant,
)
from apps.users.models import EmployeeProfile, Role, User


class RestaurantOverviewApiTests(APITestCase):
    LIST_ROW_KEYS = {
        'id',
        'parentId',
        'parentName',
        'branchType',
        'name',
        'legalName',
        'taxNumber',
        'phone',
        'address',
        'isActive',
        'restaurantAccessActive',
        'activationType',
        'activatedAt',
        'deactivatedAt',
        'tariff',
        'branchCount',
        'activeUsersCount',
        'activeDeviceCount',
        'onlineDeviceCount',
        'lastSeenAt',
        'createdAt',
        'updatedAt',
    }

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.business_partner_role = Role.objects.get(code='business_partner')
        cls.partner = BusinessPartner.objects.create(
            inn='301111111',
            company_name='Overview Partner',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.partner_user = User.objects.create_user(
            username='overview-partner',
            password='secret123',
            full_name='Overview Partner',
            role=cls.business_partner_role,
            business_partner=cls.partner,
            is_staff=True,
            is_active=True,
        )
        cls.superuser = User.objects.create_superuser(
            username='overview-superuser',
            password='secret123',
            full_name='Overview Superuser',
        )
        cls.tariff = Tariff.objects.create(
            name='Overview Tariff',
            is_active=True,
        )

        cls.root = Restaurant.objects.create(
            business_partner=cls.partner,
            name='Atlas Restaurant',
            legal_name='Atlas Restaurant MCHJ',
            tax_number='309876543',
            phone='+998901112233',
            address='Tashkent, Amir Temur 10',
            is_active=True,
            activated_at=now - timedelta(days=30),
        )
        cls.branch = Restaurant.objects.create(
            business_partner=cls.partner,
            parent_restaurant=cls.root,
            name='Chilonzor Branch',
            legal_name='Atlas Chilonzor MCHJ',
            tax_number='309876544',
            phone='+998901112244',
            address='Tashkent, Chilonzor 5',
            is_active=True,
            activated_at=now - timedelta(days=20),
        )
        cls.draft = Restaurant.objects.create(
            business_partner=cls.partner,
            name='Draft Restaurant',
            address='Bukhara',
            is_active=False,
        )
        cls.inactive = Restaurant.objects.create(
            business_partner=cls.partner,
            name='Inactive Restaurant',
            is_active=False,
            activated_at=now - timedelta(days=60),
            deactivated_at=now - timedelta(days=2),
        )
        cls.mismatch = Restaurant.objects.create(
            business_partner=cls.partner,
            name='Mismatch Restaurant',
            is_active=True,
        )
        for restaurant, entitlement_active in (
            (cls.root, True),
            (cls.branch, True),
            (cls.inactive, False),
            (cls.mismatch, False),
        ):
            RestaurantEntitlement.objects.create(
                restaurant=restaurant,
                tariff=cls.tariff,
                is_active=entitlement_active,
            )

        cls.foreign_partner = BusinessPartner.objects.create(
            inn='302222222',
            company_name='Foreign Partner',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.malformed_foreign_branch = Restaurant.objects.create(
            business_partner=cls.foreign_partner,
            parent_restaurant=cls.root,
            name='Foreign malformed branch',
            is_active=True,
        )

        cls.root_user_one = User.objects.create_user(
            username='overview-root-user-one',
            full_name='Root User One',
            restaurant=cls.root,
            is_active=True,
        )
        cls.root_user_two = User.objects.create_user(
            username='overview-root-user-two',
            full_name='Root User Two',
            restaurant=cls.root,
            is_active=True,
        )
        cls.excluded_root_user = User.objects.create_user(
            username='overview-root-user-inactive-employee',
            full_name='Inactive Employee',
            restaurant=cls.root,
            is_active=True,
        )
        EmployeeProfile.objects.filter(user=cls.excluded_root_user).update(
            employment_status=EmployeeProfile.EmploymentStatus.INACTIVE
        )
        cls.branch_user = User.objects.create_user(
            username='overview-branch-user',
            full_name='Branch User',
            restaurant=cls.branch,
            is_active=True,
        )

        cls.root_latest_seen_at = now - timedelta(minutes=2)
        cls._create_device(
            restaurant=cls.root,
            name='Root online POS',
            lease_expires_at=now + timedelta(minutes=10),
            last_seen_at=cls.root_latest_seen_at,
        )
        cls._create_device(
            restaurant=cls.root,
            name='Root offline POS',
            lease_expires_at=now - timedelta(minutes=10),
            last_seen_at=now - timedelta(minutes=5),
        )
        cls._create_device(
            restaurant=cls.root,
            name='Root revoked POS',
            lease_expires_at=now + timedelta(minutes=10),
            last_seen_at=now,
            revoked_at=now,
        )
        cls._create_device(
            restaurant=cls.root,
            name='Root control device',
            device_type=Device.Type.CONTROL_DEVICE,
            lease_expires_at=now + timedelta(minutes=10),
            last_seen_at=now,
        )
        cls._create_device(
            restaurant=cls.branch,
            name='Branch online POS',
            lease_expires_at=now + timedelta(minutes=10),
            last_seen_at=now - timedelta(minutes=1),
        )

        DistributionPoint.objects.filter(restaurant=cls.root).update(is_active=False)
        for model, name in (
            (CashDesk, 'Cash desk'),
            (PrepStation, 'Prep station'),
            (DistributionPoint, 'Distribution point'),
            (CatalogItem, 'Menu item'),
        ):
            model.objects.create(restaurant=cls.root, name=f'Active {name}')
            model.objects.create(
                restaurant=cls.root,
                name=f'Inactive {name}',
                is_active=False,
            )

    @classmethod
    def _create_device(
        cls,
        *,
        restaurant,
        name,
        lease_expires_at,
        last_seen_at,
        device_type=Device.Type.POS_TERMINAL,
        revoked_at=None,
    ):
        return Device.objects.create(
            restaurant=restaurant,
            type=device_type,
            name=name,
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key='test-public-key',
            public_key_fingerprint=uuid4().hex,
            paired_at=timezone.now() - timedelta(days=1),
            lease_expires_at=lease_expires_at,
            last_seen_at=last_seen_at,
            revoked_at=revoked_at,
        )

    def setUp(self):
        self.client.force_authenticate(self.partner_user)

    def _list_rows(self, **query):
        response = self.client.get('/api/v1/admin/restaurants/', query)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.json()['data']

    def test_list_returns_compact_contract_and_annotated_metrics(self):
        rows = self._list_rows(pageSize=100)
        rows_by_id = {row['id']: row for row in rows}
        root_row = rows_by_id[str(self.root.id)]
        branch_row = rows_by_id[str(self.branch.id)]

        self.assertEqual(set(root_row), self.LIST_ROW_KEYS)
        self.assertEqual(root_row['branchType'], 'root')
        self.assertEqual(root_row['branchCount'], 1)
        self.assertEqual(root_row['activeUsersCount'], 2)
        self.assertEqual(root_row['activeDeviceCount'], 2)
        self.assertEqual(root_row['onlineDeviceCount'], 1)
        self.assertEqual(
            parse_datetime(root_row['lastSeenAt']),
            self.root_latest_seen_at,
        )
        self.assertTrue(root_row['restaurantAccessActive'])
        self.assertEqual(branch_row['branchType'], 'branch')
        self.assertEqual(branch_row['parentId'], str(self.root.id))
        self.assertEqual(branch_row['parentName'], self.root.name)
        self.assertNotIn(str(self.malformed_foreign_branch.id), rows_by_id)

    def test_search_branch_type_and_metric_ordering(self):
        cases = (
            ({'search': self.root.tax_number}, {str(self.root.id)}),
            ({'search': 'Amir Temur'}, {str(self.root.id)}),
            (
                {'search': self.root.name, 'branchType': 'branch'},
                {str(self.branch.id)},
            ),
        )
        for query, expected_ids in cases:
            with self.subTest(query=query):
                self.assertEqual(
                    {row['id'] for row in self._list_rows(**query)},
                    expected_ids,
                )

        root_rows = self._list_rows(branchType='root', pageSize=100)
        branch_rows = self._list_rows(branchType='branch', pageSize=100)
        ordered_rows = self._list_rows(ordering='-activeUsersCount', pageSize=100)

        self.assertTrue(all(row['branchType'] == 'root' for row in root_rows))
        self.assertEqual([row['id'] for row in branch_rows], [str(self.branch.id)])
        self.assertEqual(ordered_rows[0]['id'], str(self.root.id))

    def test_list_query_count_does_not_grow_per_restaurant(self):
        with CaptureQueriesContext(connection) as baseline_queries:
            response = self.client.get(
                '/api/v1/admin/restaurants/',
                {'pageSize': 100},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        for index in range(4):
            restaurant = Restaurant.objects.create(
                business_partner=self.partner,
                name=f'Additional restaurant {index}',
            )
            RestaurantEntitlement.objects.create(
                restaurant=restaurant,
                tariff=self.tariff,
                is_active=True,
            )

        with CaptureQueriesContext(connection) as expanded_queries:
            response = self.client.get(
                '/api/v1/admin/restaurants/',
                {'pageSize': 100},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertLessEqual(len(expanded_queries), len(baseline_queries) + 1)

    @patch(
        'apps.restaurants.api.admin.serializers.restaurant_detail.restaurant_setup_readiness'
    )
    def test_detail_returns_operational_branches_and_compact_readiness(self, readiness):
        readiness.return_value = {
            'ready': False,
            'progressPercent': 43,
            'blockingIssueCount': 1,
            'steps': [
                {
                    'id': 'profile',
                    'status': 'blocked',
                    'issues': [
                        {'code': 'missing_phone', 'blocking': False},
                        {'code': 'missing_tax_number', 'blocking': True},
                    ],
                }
            ],
        }

        response = self.client.get(
            f'/api/v1/admin/restaurants/{self.root.id}/detail/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        payload = response.json()
        operational_summary = payload['operationalSummary']
        last_seen_at = operational_summary.pop('lastSeenAt')
        self.assertEqual(
            operational_summary,
            {
                'activeUsers': 2,
                'cashDesks': 1,
                'prepStations': 1,
                'distributionPoints': 1,
                'menuItems': 1,
                'activeDevices': 2,
                'onlineDevices': 1,
            },
        )
        self.assertEqual(parse_datetime(last_seen_at), self.root_latest_seen_at)
        self.assertEqual(len(payload['branches']), 1)
        self.assertEqual(payload['branches'][0]['id'], str(self.branch.id))
        self.assertEqual(payload['branches'][0]['activeUsersCount'], 1)
        self.assertEqual(payload['branches'][0]['activeDeviceCount'], 1)
        self.assertEqual(payload['branches'][0]['onlineDeviceCount'], 1)
        self.assertEqual(
            payload['setupReadiness'],
            {
                'ready': False,
                'progressPercent': 43,
                'blockingIssueCount': 1,
                'steps': [
                    {
                        'id': 'profile',
                        'status': 'blocked',
                        'issueCount': 2,
                        'blockingIssueCount': 1,
                        'issueCodes': ['missing_phone', 'missing_tax_number'],
                    }
                ],
            },
        )

    def test_portfolio_summary_is_partner_scoped(self):
        response = self.client.get(
            '/api/v1/admin/restaurants/portfolio-summary/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            response.json(),
            {
                'totalCount': 5,
                'rootCount': 4,
                'branchCount': 1,
                'activeCount': 2,
                'inactiveCount': 1,
                'draftCount': 1,
                'accessMismatchCount': 1,
                'withoutTariffCount': 1,
                'activeUsersCount': 3,
                'activeDeviceCount': 3,
                'onlineDeviceCount': 2,
            },
        )

    def test_direct_status_change_is_rejected_but_same_value_and_create_work(self):
        same_value = self.client.patch(
            f'/api/v1/admin/restaurants/{self.root.id}/',
            {'isActive': True, 'address': 'Updated address'},
            format='json',
        )
        changed_patch = self.client.patch(
            f'/api/v1/admin/restaurants/{self.root.id}/',
            {'isActive': False},
            format='json',
        )
        changed_put = self.client.put(
            f'/api/v1/admin/restaurants/{self.root.id}/',
            {'name': self.root.name, 'isActive': False},
            format='json',
        )
        created = self.client.post(
            '/api/v1/admin/restaurants/',
            {'name': 'New draft restaurant', 'isActive': False},
            format='json',
        )

        self.assertEqual(same_value.status_code, status.HTTP_200_OK, same_value.data)
        self.assertEqual(changed_patch.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('isActive', changed_patch.json())
        self.assertEqual(changed_put.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('isActive', changed_put.json())
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertFalse(created.json()['isActive'])
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)
        self.assertEqual(self.root.address, 'Updated address')
