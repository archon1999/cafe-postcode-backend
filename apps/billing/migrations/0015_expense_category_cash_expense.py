from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0014_payment_edge_operation_id'),
        ('restaurants', '0020_remove_unikassa_provider'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='cashshift',
            name='expense_total',
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='ExpenseCategory',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=120)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expense_categories_created', to=settings.AUTH_USER_MODEL)),
                ('restaurant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expense_categories', to='restaurants.restaurant')),
            ],
            options={'ordering': ('sort_order', 'name')},
        ),
        migrations.CreateModel(
            name='CashExpense',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('amount', models.PositiveBigIntegerField()),
                ('comment', models.CharField(blank=True, max_length=500)),
                ('category_name_snapshot', models.CharField(max_length=120)),
                ('recipient_name_snapshot', models.CharField(blank=True, max_length=150)),
                ('status', models.CharField(choices=[('posted', 'Posted'), ('voided', 'Voided')], default='posted', max_length=20)),
                ('occurred_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('voided_at', models.DateTimeField(blank=True, null=True)),
                ('void_reason', models.CharField(blank=True, max_length=500)),
                ('edge_operation_id', models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ('cash_desk', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cash_expenses', to='restaurants.cashdesk')),
                ('cash_shift', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='expenses', to='billing.cashshift')),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='expenses', to='billing.expensecategory')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cash_expenses_created', to=settings.AUTH_USER_MODEL)),
                ('recipient', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cash_expenses_received', to=settings.AUTH_USER_MODEL)),
                ('restaurant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cash_expenses', to='restaurants.restaurant')),
                ('voided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cash_expenses_voided', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-occurred_at', '-created_at')},
        ),
        migrations.AddConstraint(
            model_name='expensecategory',
            constraint=models.UniqueConstraint(fields=('restaurant', 'name'), name='expense_category_restaurant_name_uniq'),
        ),
        migrations.AddIndex(
            model_name='expensecategory',
            index=models.Index(fields=['restaurant', 'is_active', 'sort_order'], name='expense_category_scope_idx'),
        ),
        migrations.AddIndex(
            model_name='cashexpense',
            index=models.Index(fields=['restaurant', 'occurred_at'], name='cash_expense_scope_time_idx'),
        ),
        migrations.AddIndex(
            model_name='cashexpense',
            index=models.Index(fields=['cash_shift', 'status'], name='cash_expense_shift_status_idx'),
        ),
        migrations.AddIndex(
            model_name='cashexpense',
            index=models.Index(fields=['category', 'occurred_at'], name='cash_expense_category_time_idx'),
        ),
    ]
