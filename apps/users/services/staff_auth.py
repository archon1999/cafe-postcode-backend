from dataclasses import dataclass
from datetime import timedelta
from secrets import token_urlsafe
from time import sleep

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from apps.users.models import AuthSession, StaffInvite, StaffRefreshFamily, StaffRefreshToken, User
from apps.users.services.auth_sessions import AuthSessionService
from common.api.client_ip import get_client_ip


REFRESH_RACE_GRACE = timedelta(seconds=5)


class StaffAuthError(Exception):
    def __init__(self, code, detail, http_status=401):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.http_status = http_status


@dataclass(frozen=True)
class StaffCredentials:
    access_token: str
    access_session: AuthSession
    refresh_token: str
    refresh_family: StaffRefreshFamily


def staff_user_is_eligible(user):
    if not user or not user.is_active or not user.restaurant_access_active:
        return False
    if user.get_restaurant_scope() is None:
        return False
    profile = getattr(user, 'employee_profile', None)
    return profile is None or profile.employment_status == profile.EmploymentStatus.ACTIVE


class StaffAuthService:
    @transaction.atomic
    def create_invite(self, *, actor, employee):
        if not staff_user_is_eligible(employee):
            raise StaffAuthError('employee_inactive', 'Employee is not active.', 400)
        now = timezone.now()
        StaffInvite.objects.filter(user=employee, used_at__isnull=True, revoked_at__isnull=True).update(
            revoked_at=now, updated_at=now,
        )
        raw_token = token_urlsafe(48)
        invite = StaffInvite.objects.create(
            user=employee,
            restaurant=employee.get_restaurant_scope(),
            issued_by=actor,
            token_hash=StaffInvite.hash_token(raw_token),
            expires_at=now + timedelta(seconds=settings.STAFF_INVITE_TTL_SECONDS),
        )
        return raw_token, invite

    @transaction.atomic
    def accept_invite(self, *, raw_token, password, request):
        now = timezone.now()
        invite = StaffInvite.objects.select_for_update().select_related('user', 'restaurant').filter(
            token_hash=StaffInvite.hash_token(raw_token),
        ).first()
        if not invite or invite.used_at or invite.revoked_at or invite.expires_at <= now:
            raise StaffAuthError('invite_invalid', 'Invite is invalid or expired.', 400)
        user = invite.user
        if invite.restaurant_id != getattr(user.get_restaurant_scope(), 'pk', None) or not staff_user_is_eligible(user):
            raise StaffAuthError('invite_invalid', 'Invite is invalid or expired.', 400)
        try:
            validate_password(password, user=user)
        except DjangoValidationError as exc:
            raise StaffAuthError('weak_password', '; '.join(exc.messages), 400) from exc
        user.set_password(password)
        user.save(update_fields=['password', 'updated_at'])
        invite.used_at = now
        invite.save(update_fields=['used_at', 'updated_at'])
        StaffRefreshFamily.objects.filter(user=user, status=StaffRefreshFamily.Status.ACTIVE).update(
            status=StaffRefreshFamily.Status.REVOKED, revoked_at=now, updated_at=now,
        )
        AuthSession.objects.filter(user=user, surface=AuthSession.Surface.STAFF, status=AuthSession.Status.ACTIVE).update(
            status=AuthSession.Status.REVOKED, revoked_at=now, updated_at=now,
        )
        return self.issue_credentials(user=user, request=request)

    @transaction.atomic
    def issue_credentials(self, *, user, request):
        if not staff_user_is_eligible(user) or not user.has_usable_password():
            raise StaffAuthError('invalid_credentials', 'Invalid credentials.')
        raw_refresh = token_urlsafe(48)
        family = StaffRefreshFamily.objects.create(
            user=user,
            restaurant=user.get_restaurant_scope(),
            absolute_expires_at=timezone.now() + timedelta(seconds=settings.STAFF_REFRESH_ABSOLUTE_TTL_SECONDS),
            client_ip=get_client_ip(request),
            user_agent=request.headers.get('User-Agent', '')[:255],
        )
        StaffRefreshToken.objects.create(family=family, token_hash=StaffRefreshToken.hash_token(raw_refresh))
        raw_access, session = AuthSessionService().issue(
            user=user,
            request=request,
            surface=AuthSession.Surface.STAFF,
            restaurant=family.restaurant,
            staff_refresh_family=family,
        )
        return StaffCredentials(raw_access, session, raw_refresh, family)

    def rotate_refresh(self, *, raw_token, request):
        if not raw_token:
            raise StaffAuthError('refresh_invalid', 'Refresh session is invalid.')
        # SQLite is used only for local development. Its select_for_update() is a
        # no-op, and two readers upgrading to writers can raise SQLITE_BUSY
        # immediately, regardless of the configured busy timeout. Retry the
        # whole transaction after it rolls back; PostgreSQL retains row locks.
        for attempt in range(6):
            try:
                return self._rotate_refresh_once(raw_token=raw_token, request=request)
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower() or attempt == 5:
                    raise
                sleep(0.025 * (2 ** attempt))

    def _rotate_refresh_once(self, *, raw_token, request):
        now = timezone.now()
        failure = None
        result = None
        with transaction.atomic():
            # Lock only the credentials being rotated. Locking joined user or
            # restaurant rows would serialize otherwise independent families.
            refresh = StaffRefreshToken.objects.select_for_update(of=('self',)).select_related('family__user').filter(
                token_hash=StaffRefreshToken.hash_token(raw_token),
            ).first()
            if refresh is None:
                failure = StaffAuthError('refresh_invalid', 'Refresh session is invalid.')
            else:
                family = StaffRefreshFamily.objects.select_for_update(of=('self',)).select_related('user', 'restaurant').get(pk=refresh.family_id)
                if refresh.used_at is not None:
                    if (
                        family.status == StaffRefreshFamily.Status.ACTIVE
                        and family.absolute_expires_at > now
                        and now - refresh.used_at <= REFRESH_RACE_GRACE
                    ):
                        # Two tabs can send the same cookie before the first
                        # rotation response reaches the browser. Never mint a
                        # second credential or clear the newer cookie here.
                        failure = StaffAuthError('refresh_raced', 'Refresh session was just rotated.', 409)
                    else:
                        self._revoke_family(family, now=now)
                        failure = StaffAuthError('refresh_reused', 'Refresh session was reused.')
                elif family.status != StaffRefreshFamily.Status.ACTIVE or family.absolute_expires_at <= now:
                    self._revoke_family(family, now=now)
                    failure = StaffAuthError('refresh_expired', 'Refresh session is expired or revoked.')
                elif family.restaurant_id != getattr(family.user.get_restaurant_scope(), 'pk', None) or not staff_user_is_eligible(family.user):
                    self._revoke_family(family, now=now)
                    failure = StaffAuthError('refresh_invalid', 'Refresh session is invalid.')
                else:
                    next_raw = token_urlsafe(48)
                    next_token = StaffRefreshToken.objects.create(
                        family=family, token_hash=StaffRefreshToken.hash_token(next_raw),
                    )
                    refresh.used_at = now
                    refresh.replaced_by = next_token
                    refresh.save(update_fields=['used_at', 'replaced_by', 'updated_at'])
                    raw_access, session = AuthSessionService().issue(
                        user=family.user,
                        request=request,
                        surface=AuthSession.Surface.STAFF,
                        restaurant=family.restaurant,
                        staff_refresh_family=family,
                    )
                    result = StaffCredentials(raw_access, session, next_raw, family)
        if failure:
            raise failure
        return result

    def revoke_by_cookie(self, *, raw_token):
        if not raw_token:
            return
        with transaction.atomic():
            token = StaffRefreshToken.objects.select_related('family').filter(
                token_hash=StaffRefreshToken.hash_token(raw_token),
            ).first()
            if token:
                family = StaffRefreshFamily.objects.select_for_update().get(pk=token.family_id)
                self._revoke_family(family, now=timezone.now())

    @staticmethod
    def _revoke_family(family, *, now):
        if family.status != StaffRefreshFamily.Status.REVOKED:
            family.status = StaffRefreshFamily.Status.REVOKED
            family.revoked_at = now
            family.save(update_fields=['status', 'revoked_at', 'updated_at'])
        AuthSession.objects.filter(staff_refresh_family=family, status=AuthSession.Status.ACTIVE).update(
            status=AuthSession.Status.REVOKED, revoked_at=now, updated_at=now,
        )
