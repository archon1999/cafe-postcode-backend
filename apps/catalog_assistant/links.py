import hashlib
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from .access import restaurants_for
from .models import ManagementBotAccount, ManagementBotLink


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def issue_link(user):
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if not restaurants_for(user).exists():
        raise PermissionDenied('Boshqarish uchun ruxsat berilgan shahobcha topilmadi.')
    username = getattr(settings, 'MANAGEMENT_BOT_USERNAME', '').strip().lstrip('@')
    if not username:
        raise ValidationError('Telegram boshqaruv boti hali sozlanmagan.')
    now = timezone.now()
    ManagementBotLink.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=now)
    raw = secrets.token_urlsafe(32)
    link = ManagementBotLink.objects.create(user=user, token_hash=token_hash(raw), expires_at=now + timedelta(minutes=5))
    return {'url': f'https://t.me/{username}?start={raw}', 'expires_at': link.expires_at.isoformat()}


@transaction.atomic
def consume_link(token, telegram_user_id, chat_id):
    # Lock the owner first, matching issue_link's lock order.
    candidate = ManagementBotLink.objects.filter(token_hash=token_hash(token)).first()
    if candidate is None:
        raise ValidationError('Havola eskirgan yoki ishlatilgan. Admin paneldan yangisini oling.')
    user = get_user_model().objects.select_for_update().get(pk=candidate.user_id)
    link = ManagementBotLink.objects.select_for_update().get(pk=candidate.pk)
    if link.consumed_at or link.expires_at <= timezone.now() or not restaurants_for(user).exists():
        raise ValidationError('Havola eskirgan yoki ishlatilgan. Admin paneldan yangisini oling.')
    if ManagementBotAccount.objects.filter(telegram_user_id=telegram_user_id).exclude(user=user).exists():
        raise ValidationError('Bu Telegram akkaunti boshqa foydalanuvchiga ulangan. Avval /disconnect qiling.')
    account, _ = ManagementBotAccount.objects.update_or_create(user=user, defaults={
        'telegram_user_id': telegram_user_id, 'chat_id': chat_id, 'state': {}, 'restaurant': None,
    })
    link.consumed_at = timezone.now()
    link.save(update_fields=['consumed_at', 'updated_at'])
    return account
