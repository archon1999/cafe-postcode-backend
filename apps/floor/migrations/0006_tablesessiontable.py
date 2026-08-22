import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ('floor', '0005_integer_hall_and_table_service_fees'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TableSessionTable',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('released_at', models.DateTimeField(blank=True, null=True)),
                (
                    'joined_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='joined_table_session_tables',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'session',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='attached_table_links',
                        to='floor.tablesession',
                    ),
                ),
                (
                    'table',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='attached_session_links',
                        to='floor.diningtable',
                    ),
                ),
            ],
            options={
                'ordering': ('created_at',),
                'indexes': [
                    models.Index(fields=['table', 'released_at'], name='tblsess_tbl_table_rel_idx'),
                    models.Index(fields=['session', 'released_at'], name='tblsess_tbl_sess_rel_idx'),
                ],
                'constraints': [
                    models.UniqueConstraint(fields=('session', 'table'), name='tblsess_table_session_table_uniq'),
                ],
            },
        ),
    ]
