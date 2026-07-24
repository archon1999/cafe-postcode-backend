import uuid

from django.utils import timezone
from rest_framework import status

from apps.billing.models import CashExpense, CashShift, ExpenseCategory
from apps.restaurants.models import Restaurant
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import User


class CashExpenseApiTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.expense_category = ExpenseCategory.objects.create(
            restaurant=self.restaurant,
            name='Transport',
            sort_order=1,
            created_by=self.user,
        )
        self.recipient = User.objects.create_user(
            username='expense-recipient',
            password='secret123',
            full_name='Expense Recipient',
            restaurant=self.restaurant,
            role=self.role,
        )

    def open_expense_shift(self, opening_cash_amount=1000):
        response = self.open_shift_via_api(
            cash_desk_id=self.cash_desk.id,
            opening_cash_amount=opening_cash_amount,
        )
        return CashShift.objects.get(pk=response['current_shift']['id'])

    def create_expense(self, **overrides):
        payload = {
            'amount': 300,
            'category_id': str(self.expense_category.id),
            'comment': 'Yetkazib berish',
            'recipient_id': str(self.recipient.id),
            **overrides,
        }
        return self.client.post('/api/v1/pos/billing/shifts/current/expenses/', payload, format='json')

    def test_context_create_list_and_void_keep_cash_drawer_consistent(self):
        shift = self.open_expense_shift()

        context = self.client.get('/api/v1/pos/billing/context/')
        self.assertEqual(context.status_code, status.HTTP_200_OK, context.data)
        self.assertEqual(context.data['expense_categories'][0]['name'], 'Transport')
        self.assertIn(str(self.recipient.id), {str(row['id']) for row in context.data['expense_recipients']})

        created = self.create_expense()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertEqual(created.data['amount'], 300)
        self.assertEqual(created.data['category_name'], 'Transport')
        self.assertEqual(str(created.data['cash_shift_id']), str(shift.id))

        current = self.client.get('/api/v1/pos/billing/context/').data['current_shift']
        self.assertEqual(current['expense_total'], 300)
        self.assertEqual(current['expected_closing_cash_amount'], 700)

        listed = self.client.get('/api/v1/pos/billing/shifts/current/expenses/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.data)
        self.assertEqual([str(row['id']) for row in listed.data], [str(created.data['id'])])

        voided = self.client.post(
            f"/api/v1/pos/billing/expenses/{created.data['id']}/void/",
            {'reason': 'Xato kiritildi'},
            format='json',
        )
        self.assertEqual(voided.status_code, status.HTTP_200_OK, voided.data)
        self.assertEqual(voided.data['status'], CashExpense.Status.VOIDED)
        current = self.client.get('/api/v1/pos/billing/context/').data['current_shift']
        self.assertEqual(current['expense_total'], 0)
        self.assertEqual(current['expected_closing_cash_amount'], 1000)

    def test_create_rejects_amount_above_available_cash_and_foreign_scope(self):
        self.open_expense_shift(opening_cash_amount=200)
        too_large = self.create_expense(amount=201)
        self.assertEqual(too_large.status_code, status.HTTP_400_BAD_REQUEST, too_large.data)
        self.assertEqual(int(too_large.data['availableCashAmount']), 200)

        other_restaurant = Restaurant.objects.create(name='Other restaurant')
        foreign_category = ExpenseCategory.objects.create(
            restaurant=other_restaurant,
            name='Foreign',
            created_by=self.user,
        )
        foreign = self.create_expense(amount=100, category_id=str(foreign_category.id))
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST, foreign.data)
        self.assertFalse(CashExpense.objects.filter(category=foreign_category).exists())

    def test_edge_operation_is_idempotent_and_preserves_offline_uuid(self):
        self.open_expense_shift()
        expense_id = uuid.uuid4()
        operation_id = f'edge:{uuid.uuid4()}'
        payload = {
            'id': str(expense_id),
            'amount': 250,
            'category_id': str(self.expense_category.id),
            'edge_operation_id': operation_id,
        }
        first = self.client.post(
            '/api/v1/pos/billing/shifts/current/expenses/',
            payload,
            format='json',
            HTTP_X_EDGE_OPERATION_ID=operation_id,
        )
        second = self.client.post(
            '/api/v1/pos/billing/shifts/current/expenses/',
            payload,
            format='json',
            HTTP_X_EDGE_OPERATION_ID=operation_id,
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)
        self.assertEqual(str(first.data['id']), str(expense_id))
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(CashExpense.objects.filter(edge_operation_id=operation_id).count(), 1)

    def test_expense_from_closed_shift_cannot_be_voided(self):
        shift = self.open_expense_shift()
        created = self.create_expense()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        shift.status = CashShift.Status.CLOSED
        shift.closed_at = timezone.now()
        shift.closed_by = self.user
        shift.save(update_fields=('status', 'closed_at', 'closed_by', 'updated_at'))

        response = self.client.post(
            f"/api/v1/pos/billing/expenses/{created.data['id']}/void/",
            {'reason': 'Late correction'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(CashExpense.objects.get(pk=created.data['id']).status, CashExpense.Status.POSTED)

    def test_admin_can_manage_categories_and_audit_expenses(self):
        self.open_expense_shift()
        created = self.create_expense()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)

        category_create = self.client.post(
            '/api/v1/admin/billing/expense-categories/',
            {'name': 'Ijara', 'sort_order': 2, 'is_active': True},
            format='json',
        )
        self.assertEqual(category_create.status_code, status.HTTP_201_CREATED, category_create.data)
        category_update = self.client.patch(
            f"/api/v1/admin/billing/expense-categories/{category_create.data['id']}/",
            {'is_active': False},
            format='json',
        )
        self.assertEqual(category_update.status_code, status.HTTP_200_OK, category_update.data)
        self.assertFalse(category_update.data['is_active'])

        listed = self.client.get('/api/v1/admin/billing/expenses/?status_in=posted&page_size=1')
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.data)
        self.assertEqual(listed.data['total'], 1)
        self.assertEqual(listed.data['pageSize'], 1)
        self.assertEqual(listed.data['postedTotal'], 300)
        self.assertEqual(str(listed.data['data'][0]['id']), str(created.data['id']))

        filtered_by_categories = self.client.get(
            f"/api/v1/admin/billing/expenses/?category_id_in={self.expense_category.id},{category_create.data['id']}"
        )
        self.assertEqual(filtered_by_categories.status_code, status.HTTP_200_OK, filtered_by_categories.data)
        self.assertEqual(filtered_by_categories.data['total'], 1)

        excluded_category = self.client.get(
            f"/api/v1/admin/billing/expenses/?category_id_in={category_create.data['id']}"
        )
        self.assertEqual(excluded_category.status_code, status.HTTP_200_OK, excluded_category.data)
        self.assertEqual(excluded_category.data['total'], 0)
        self.assertEqual(excluded_category.data['postedTotal'], 0)

        voided = self.client.post(
            f"/api/v1/admin/billing/expenses/{created.data['id']}/void/",
            {'reason': 'Admin correction'},
            format='json',
        )
        self.assertEqual(voided.status_code, status.HTTP_200_OK, voided.data)
        self.assertEqual(voided.data['void_reason'], 'Admin correction')
