from django.db.models.signals import m2m_changed, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.users.models import AdminRefreshFamily, AdminRefreshToken, AuthSession, Role, User


SENSITIVE_USER_FIELDS = ('password', 'role_id', 'is_active', 'is_staff', 'is_superuser')


def revoke_user_sessions(user_id) -> None:
    now = timezone.now()
    Token.objects.filter(user_id=user_id).delete()
    family_ids = list(
        AdminRefreshFamily.objects.filter(user_id=user_id, status=AdminRefreshFamily.Status.ACTIVE).values_list(
            'id', flat=True
        )
    )
    AdminRefreshFamily.objects.filter(id__in=family_ids).update(
        status=AdminRefreshFamily.Status.REVOKED,
        revoked_at=now,
        updated_at=now,
    )
    AdminRefreshToken.objects.filter(family_id__in=family_ids, revoked_at__isnull=True).update(
        revoked_at=now,
        updated_at=now,
    )
    AuthSession.objects.filter(user_id=user_id, status=AuthSession.Status.ACTIVE).update(
        status=AuthSession.Status.REVOKED,
        revoked_at=now,
        last_seen_at=now,
        updated_at=now,
    )


@receiver(pre_save, sender=User)
def detect_sensitive_user_change(sender, instance, **kwargs):
    if not instance.pk:
        instance._revoke_auth_sessions_after_save = False
        return
    previous = sender.objects.filter(pk=instance.pk).values(*SENSITIVE_USER_FIELDS).first()
    instance._revoke_auth_sessions_after_save = bool(
        previous and any(previous[field] != getattr(instance, field) for field in SENSITIVE_USER_FIELDS)
    )


@receiver(post_save, sender=User)
def revoke_sessions_after_sensitive_user_change(sender, instance, created, **kwargs):
    if not created and getattr(instance, '_revoke_auth_sessions_after_save', False):
        revoke_user_sessions(instance.pk)


@receiver(m2m_changed, sender=Role.permissions.through)
def revoke_sessions_after_role_permissions_change(sender, instance, action, **kwargs):
    if action in {'post_add', 'post_remove', 'post_clear'}:
        for user_id in User.objects.filter(role=instance).values_list('id', flat=True).iterator():
            revoke_user_sessions(user_id)
