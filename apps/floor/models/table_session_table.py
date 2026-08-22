from django.conf import settings
from django.db import models

from common.models import BaseModel


class TableSessionTable(BaseModel):
    """A secondary physical table attached to one logical table session."""

    session = models.ForeignKey(
        'floor.TableSession',
        on_delete=models.CASCADE,
        related_name='attached_table_links',
    )
    table = models.ForeignKey(
        'floor.DiningTable',
        on_delete=models.CASCADE,
        related_name='attached_session_links',
    )
    joined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='joined_table_session_tables',
        null=True,
        blank=True,
    )
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('session', 'table'),
                name='tblsess_table_session_table_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=('table', 'released_at'), name='tblsess_tbl_table_rel_idx'),
            models.Index(fields=('session', 'released_at'), name='tblsess_tbl_sess_rel_idx'),
        ]
