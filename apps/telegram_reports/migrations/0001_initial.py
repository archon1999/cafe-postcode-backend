import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("restaurants", "0020_remove_unikassa_provider"),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramAccount",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("telegram_user_id", models.BigIntegerField(unique=True)),
                ("chat_id", models.BigIntegerField()),
                ("username", models.CharField(blank=True, max_length=255)),
                ("first_name", models.CharField(blank=True, max_length=255)),
                ("language_code", models.CharField(blank=True, max_length=16)),
                ("notifications_enabled", models.BooleanField(default=True)),
                ("state", models.CharField(choices=[("idle", "Idle"), ("awaiting_connect", "Awaiting branch codes")], default="idle", max_length=32)),
                ("last_interaction_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ("telegram_user_id",)},
        ),
        migrations.CreateModel(
            name="TelegramProcessedUpdate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("update_id", models.BigIntegerField(unique=True)),
                ("status", models.CharField(choices=[("processing", "Processing"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="processing", max_length=20)),
                ("error", models.TextField(blank=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="TelegramBranchSubscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="branch_subscriptions", to="telegram_reports.telegramaccount")),
                ("restaurant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="telegram_subscriptions", to="restaurants.restaurant")),
            ],
            options={"ordering": ("restaurant__name",)},
        ),
        migrations.CreateModel(
            name="TelegramReportDelivery",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("report_type", models.CharField(choices=[("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")], max_length=20)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")], default="pending", max_length=20)),
                ("telegram_message_id", models.BigIntegerField(blank=True, null=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("error", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="report_deliveries", to="telegram_reports.telegramaccount")),
                ("restaurant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="telegram_report_deliveries", to="restaurants.restaurant")),
            ],
            options={
                "ordering": ("-period_end", "restaurant__name"),
                "indexes": [models.Index(fields=["status", "created_at"], name="telegram_delivery_status_idx")],
            },
        ),
        migrations.AddConstraint(
            model_name="telegrambranchsubscription",
            constraint=models.UniqueConstraint(fields=("account", "restaurant"), name="telegram_unique_account_branch"),
        ),
        migrations.AddConstraint(
            model_name="telegramreportdelivery",
            constraint=models.UniqueConstraint(fields=("account", "restaurant", "report_type", "period_start", "period_end"), name="telegram_unique_report_delivery"),
        ),
    ]

