from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import (
    get_cash_expense_model,
    get_cash_shift_model,
    get_expense_category_model,
)
from apps.users.models import EmployeeProfile, User
from common.api.permissions import POS_CASH_SHIFT_MANAGE_PERMISSION, has_permission_code

from .cash_shift import CashShiftService

CashExpense = get_cash_expense_model()
CashShift = get_cash_shift_model()
ExpenseCategory = get_expense_category_model()


class CashExpenseService:
    def get_active_categories(self, *, restaurant):
        return ExpenseCategory.objects.filter(
            restaurant=restaurant,
            is_active=True,
        ).order_by('sort_order', 'name')

    def get_available_recipients(self, *, restaurant):
        return (
            User.objects.filter(
                restaurant_profile__restaurant=restaurant,
                is_active=True,
            )
            .exclude(
                employee_profile__employment_status__in=(
                    EmployeeProfile.EmploymentStatus.INACTIVE,
                    EmployeeProfile.EmploymentStatus.ARCHIVED,
                )
            )
            .select_related('role', 'employee_profile')
            .order_by('full_name', 'username')
            .distinct()
        )

    def resolve_active_shift(self, *, restaurant, user, cash_shift_id=None):
        if cash_shift_id:
            shift = (
                CashShift.objects.select_related('cash_desk', 'cashier', 'opened_by')
                .filter(
                    pk=cash_shift_id,
                    cash_desk__restaurant=restaurant,
                    status=CashShift.Status.OPEN,
                )
                .first()
            )
            if (
                shift is not None
                and not has_permission_code(user, POS_CASH_SHIFT_MANAGE_PERMISSION)
                and shift.cashier_id != user.id
            ):
                raise ValidationError({'cashShiftId': 'Smenani tanlash uchun menejer ruxsati kerak.'})
        else:
            shift = CashShiftService().get_active_shift(restaurant=restaurant, user=user)
        if shift is None:
            raise ValidationError({'detail': 'Aktiv kassa smenasi topilmadi.'})
        return shift

    @transaction.atomic
    def create_expense(
        self,
        *,
        restaurant,
        user,
        amount,
        category_id,
        id=None,
        comment='',
        recipient_id=None,
        cash_shift_id=None,
        edge_operation_id='',
    ):
        amount = int(amount or 0)
        if amount <= 0:
            raise ValidationError({'amount': 'Summa 0 dan katta bo‘lishi kerak.'})

        edge_operation_id = str(edge_operation_id or '').strip() or None
        if edge_operation_id:
            existing = CashExpense.objects.select_related('category', 'recipient', 'cash_shift', 'cash_desk').filter(
                edge_operation_id=edge_operation_id
            ).first()
            if existing is not None:
                if (
                    existing.restaurant_id != restaurant.id
                    or existing.amount != amount
                    or str(existing.category_id) != str(category_id)
                ):
                    raise ValidationError({'edgeOperationId': 'Operation ID boshqa xarajatga tegishli.'})
                return existing

        resolved_shift = self.resolve_active_shift(
            restaurant=restaurant,
            user=user,
            cash_shift_id=cash_shift_id,
        )
        shift = (
            CashShift.objects.select_for_update()
            .select_related('cash_desk')
            .get(pk=resolved_shift.pk)
        )
        if shift.status != CashShift.Status.OPEN:
            raise ValidationError({'detail': 'Faqat aktiv smenadan xarajat qilish mumkin.'})

        category = ExpenseCategory.objects.filter(
            pk=category_id,
            restaurant=restaurant,
            is_active=True,
        ).first()
        if category is None:
            raise ValidationError({'categoryId': 'Aktiv xarajat kategoriyasi topilmadi.'})

        recipient = None
        if recipient_id:
            recipient = self.get_available_recipients(restaurant=restaurant).filter(pk=recipient_id).first()
            if recipient is None:
                raise ValidationError({'recipientId': 'Tanlangan oluvchi shu restoranga tegishli emas.'})

        available_cash = int(CashShiftService().build_shift_snapshot(shift=shift)['expected_closing_cash_amount'])
        if amount > available_cash:
            raise ValidationError(
                {
                    'amount': 'Xarajat summasi kassadagi mavjud naqd puldan katta.',
                    'availableCashAmount': available_cash,
                }
            )

        create_values = {
            'restaurant': restaurant,
            'cash_shift': shift,
            'cash_desk': shift.cash_desk,
            'category': category,
            'amount': amount,
            'comment': str(comment or '').strip(),
            'recipient': recipient,
            'created_by': user,
            'category_name_snapshot': category.name,
            'recipient_name_snapshot': (recipient.full_name or recipient.username) if recipient else '',
            'edge_operation_id': edge_operation_id,
        }
        if id is not None:
            create_values['id'] = id
        expense = CashExpense.objects.create(**create_values)
        shift.expense_total = int(shift.expense_total or 0) + amount
        shift.save(update_fields=('expense_total', 'updated_at'))
        return expense

    @transaction.atomic
    def void_expense(self, *, expense, user, reason=''):
        locked = (
            CashExpense.objects.select_for_update()
            .select_related('cash_shift')
            .get(pk=expense.pk)
        )
        shift = CashShift.objects.select_for_update().get(pk=locked.cash_shift_id)
        if locked.status == CashExpense.Status.VOIDED:
            return locked
        if shift.status != CashShift.Status.OPEN:
            raise ValidationError({'detail': 'Yopilgan smenadagi xarajatni bekor qilib bo‘lmaydi.'})
        reason = str(reason or '').strip()
        if not reason:
            raise ValidationError({'reason': 'Bekor qilish sababi majburiy.'})
        locked.status = CashExpense.Status.VOIDED
        locked.voided_at = timezone.now()
        locked.voided_by = user
        locked.void_reason = reason
        locked.save(update_fields=('status', 'voided_at', 'voided_by', 'void_reason', 'updated_at'))
        shift.expense_total = max(0, int(shift.expense_total or 0) - int(locked.amount or 0))
        shift.save(update_fields=('expense_total', 'updated_at'))
        return locked
