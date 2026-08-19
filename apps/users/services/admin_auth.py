from dataclasses import dataclass
from datetime import timedelta
from secrets import token_urlsafe

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.devices.models import SecurityEvent
from apps.devices.security import get_client_ip, record_security_event
from apps.users.models import (
    AdminMFAChallenge,
    AdminMFAProfile,
    AdminRefreshFamily,
    AdminRefreshToken,
    AuthSession,
)

from .admin_mfa import (
    consume_recovery_code,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_codes,
    provisioning_uri,
    totp_code_digest,
    verify_totp,
)
from .auth_sessions import AuthSessionService


class AdminAuthError(Exception):
    def __init__(self, code: str, detail: str, *, http_status: int = 401):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.http_status = http_status


@dataclass(frozen=True)
class AdminCredentialBundle:
    access_token: str
    access_session: AuthSession
    refresh_token: str
    refresh_family: AdminRefreshFamily


class AdminAuthService:
    access_session_service_class = AuthSessionService

    def issue_mfa_challenge(self, *, user, request) -> tuple[str, AdminMFAChallenge]:
        now = timezone.now()
        kind = (
            AdminMFAChallenge.Kind.LOGIN
            if AdminMFAProfile.objects.filter(user=user).exists()
            else AdminMFAChallenge.Kind.ENROLLMENT
        )
        AdminMFAChallenge.objects.filter(user=user, used_at__isnull=True).update(used_at=now, updated_at=now)
        raw_token = token_urlsafe(48)
        challenge = AdminMFAChallenge.objects.create(
            user=user,
            kind=kind,
            token_hash=AdminMFAChallenge.build_token_hash(raw_token),
            expires_at=now + timedelta(seconds=settings.ADMIN_MFA_CHALLENGE_TTL_SECONDS),
            client_ip=get_client_ip(request),
            user_agent=request.headers.get('User-Agent', '')[:255],
        )
        record_security_event(
            event_type='ADMIN_MFA_CHALLENGE_ISSUED',
            request=request,
            actor=user,
            severity=SecurityEvent.Severity.INFO,
            result=kind,
        )
        return raw_token, challenge

    def start_enrollment(self, *, challenge_token: str, request):
        failure = None
        payload = None
        with transaction.atomic():
            try:
                challenge = self._lock_challenge(challenge_token, expected_kind=AdminMFAChallenge.Kind.ENROLLMENT)
                if AdminMFAProfile.objects.filter(user=challenge.user).exists():
                    raise AdminAuthError('mfa_already_enrolled', 'MFA is already enrolled.', http_status=409)
                if challenge.pending_secret_encrypted:
                    secret = decrypt_mfa_secret(challenge.pending_secret_encrypted)
                else:
                    secret = generate_totp_secret()
                    challenge.pending_secret_encrypted = encrypt_mfa_secret(secret)
                    challenge.save(update_fields=['pending_secret_encrypted', 'updated_at'])
                payload = {
                    'secret': secret,
                    'otpauth_uri': provisioning_uri(secret=secret, username=challenge.user.username),
                    'expires_at': challenge.expires_at,
                }
            except AdminAuthError as error:
                failure = error
        if failure is not None:
            raise failure
        return payload

    def confirm_enrollment(self, *, challenge_token: str, code: str, request):
        failure = None
        result = None
        with transaction.atomic():
            try:
                challenge = self._lock_challenge(challenge_token, expected_kind=AdminMFAChallenge.Kind.ENROLLMENT)
                if not challenge.pending_secret_encrypted:
                    raise AdminAuthError('mfa_enrollment_not_started', 'Start MFA enrollment first.', http_status=409)
                if AdminMFAProfile.objects.filter(user=challenge.user).exists():
                    raise AdminAuthError('mfa_already_enrolled', 'MFA is already enrolled.', http_status=409)
                secret = decrypt_mfa_secret(challenge.pending_secret_encrypted)
                counter = verify_totp(secret, code)
                if counter is None:
                    self._record_challenge_failure(
                        challenge,
                        request=request,
                        event_type='ADMIN_MFA_ENROLLMENT_FAILED',
                    )
                now = timezone.now()
                recovery_codes = generate_recovery_codes()
                profile = AdminMFAProfile.objects.create(
                    user=challenge.user,
                    encrypted_secret=encrypt_mfa_secret(secret),
                    confirmed_at=now,
                    last_totp_counter=counter,
                    last_totp_code_digest=totp_code_digest(secret, code),
                    recovery_code_hashes=hash_recovery_codes(recovery_codes),
                    recovery_codes_generated_at=now,
                )
                challenge.used_at = now
                challenge.pending_secret_encrypted = ''
                challenge.save(update_fields=['used_at', 'pending_secret_encrypted', 'updated_at'])
                bundle = self.issue_credentials(user=profile.user, request=request, mfa_verified_at=now)
                record_security_event(
                    event_type='ADMIN_MFA_ENROLLED',
                    request=request,
                    actor=profile.user,
                    auth_session=bundle.access_session,
                    severity=SecurityEvent.Severity.HIGH,
                    result='success',
                )
                result = (bundle, recovery_codes)
            except AdminAuthError as error:
                failure = error
        if failure is not None:
            raise failure
        return result

    def complete_mfa_challenge(
        self,
        *,
        challenge_token: str,
        request,
        code: str = '',
        recovery_code: str = '',
    ) -> AdminCredentialBundle:
        failure = None
        bundle = None
        with transaction.atomic():
            try:
                challenge = self._lock_challenge(challenge_token, expected_kind=AdminMFAChallenge.Kind.LOGIN)
                profile = AdminMFAProfile.objects.select_for_update().filter(user=challenge.user).first()
                if profile is None:
                    raise AdminAuthError('mfa_enrollment_required', 'MFA enrollment is required.', http_status=409)
                verified = False
                event_type = 'ADMIN_MFA_CHALLENGE_FAILED'
                if code:
                    secret = decrypt_mfa_secret(profile.encrypted_secret)
                    counter = verify_totp(
                        secret,
                        code,
                        last_counter=profile.last_totp_counter,
                        last_code_digest=profile.last_totp_code_digest,
                    )
                    if counter is not None:
                        profile.last_totp_counter = counter
                        profile.last_totp_code_digest = totp_code_digest(secret, code)
                        profile.save(update_fields=['last_totp_counter', 'last_totp_code_digest', 'updated_at'])
                        verified = True
                elif recovery_code:
                    verified, remaining_hashes = consume_recovery_code(recovery_code, profile.recovery_code_hashes)
                    if verified:
                        profile.recovery_code_hashes = remaining_hashes
                        profile.save(update_fields=['recovery_code_hashes', 'updated_at'])
                        event_type = 'ADMIN_MFA_RECOVERY_CODE_USED'
                if not verified:
                    self._record_challenge_failure(challenge, request=request, event_type=event_type)
                now = timezone.now()
                challenge.used_at = now
                challenge.save(update_fields=['used_at', 'updated_at'])
                bundle = self.issue_credentials(user=profile.user, request=request, mfa_verified_at=now)
                record_security_event(
                    event_type=event_type if recovery_code else 'ADMIN_MFA_CHALLENGE_SUCCEEDED',
                    request=request,
                    actor=profile.user,
                    auth_session=bundle.access_session,
                    severity=SecurityEvent.Severity.HIGH if recovery_code else SecurityEvent.Severity.INFO,
                    result='success',
                    metadata={'remainingRecoveryCodes': len(profile.recovery_code_hashes)} if recovery_code else {},
                )
            except AdminAuthError as error:
                failure = error
        if failure is not None:
            raise failure
        return bundle

    def step_up(
        self,
        *,
        access_session: AuthSession,
        request,
        code: str = '',
        recovery_code: str = '',
    ):
        failure = None
        verified_at = None
        with transaction.atomic():
            try:
                if access_session.surface != AuthSession.Surface.ADMIN or access_session.refresh_family_id is None:
                    raise AdminAuthError('admin_session_required', 'A refresh-backed admin session is required.')
                family = (
                    AdminRefreshFamily.objects.select_for_update()
                    .select_related('user')
                    .get(pk=access_session.refresh_family_id)
                )
                failure_key = f'admin-mfa-step-up-failures:{family.pk}'
                if int(cache.get(failure_key, 0) or 0) >= settings.ADMIN_MFA_MAX_ATTEMPTS:
                    self._lock_family_after_step_up_failures(family=family, access_session=access_session, request=request)
                profile = AdminMFAProfile.objects.select_for_update().filter(user=family.user).first()
                if profile is None:
                    raise AdminAuthError('mfa_enrollment_required', 'MFA enrollment is required.', http_status=403)
                verified = False
                recovery_used = False
                if code:
                    secret = decrypt_mfa_secret(profile.encrypted_secret)
                    counter = verify_totp(
                        secret,
                        code,
                        last_counter=profile.last_totp_counter,
                        last_code_digest=profile.last_totp_code_digest,
                    )
                    if counter is not None:
                        profile.last_totp_counter = counter
                        profile.last_totp_code_digest = totp_code_digest(secret, code)
                        profile.save(update_fields=['last_totp_counter', 'last_totp_code_digest', 'updated_at'])
                        verified = True
                elif recovery_code:
                    verified, remaining_hashes = consume_recovery_code(recovery_code, profile.recovery_code_hashes)
                    if verified:
                        recovery_used = True
                        profile.recovery_code_hashes = remaining_hashes
                        profile.save(update_fields=['recovery_code_hashes', 'updated_at'])
                if not verified:
                    failed_attempts = int(cache.get(failure_key, 0) or 0) + 1
                    cache.set(failure_key, failed_attempts, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
                    record_security_event(
                        event_type='ADMIN_MFA_STEP_UP_FAILED',
                        request=request,
                        actor=family.user,
                        auth_session=access_session,
                        severity=SecurityEvent.Severity.MEDIUM,
                        result='failed',
                    )
                    if failed_attempts >= settings.ADMIN_MFA_MAX_ATTEMPTS:
                        self._lock_family_after_step_up_failures(
                            family=family,
                            access_session=access_session,
                            request=request,
                        )
                    raise AdminAuthError('mfa_code_invalid', 'MFA code is invalid.', http_status=400)
                verified_at = timezone.now()
                cache.delete(failure_key)
                family.mfa_verified_at = verified_at
                family.save(update_fields=['mfa_verified_at', 'updated_at'])
                AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).update(
                    mfa_verified_at=verified_at,
                    updated_at=verified_at,
                )
                record_security_event(
                    event_type='ADMIN_MFA_STEP_UP_SUCCEEDED',
                    request=request,
                    actor=family.user,
                    auth_session=access_session,
                    severity=SecurityEvent.Severity.HIGH if recovery_used else SecurityEvent.Severity.INFO,
                    result='recovery' if recovery_used else 'totp',
                )
            except AdminAuthError as error:
                failure = error
        if failure is not None:
            raise failure
        return verified_at

    @staticmethod
    def _lock_family_after_step_up_failures(*, family, access_session, request):
        now = timezone.now()
        if family.locked_at is None:
            family.locked_at = now
            family.save(update_fields=['locked_at', 'updated_at'])
            AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).update(
                locked_at=now,
                updated_at=now,
            )
            record_security_event(
                event_type='ADMIN_MFA_STEP_UP_LOCKED_OUT',
                request=request,
                actor=family.user,
                auth_session=access_session,
                severity=SecurityEvent.Severity.HIGH,
                result='locked',
            )
        raise AdminAuthError('session_locked', 'Admin session is locked.', http_status=423)

    @transaction.atomic
    def issue_credentials(self, *, user, request, mfa_verified_at=None) -> AdminCredentialBundle:
        if settings.ADMIN_MFA_REQUIRED and user.is_superuser and mfa_verified_at is None:
            raise AdminAuthError('mfa_required', 'MFA verification is required.', http_status=403)
        now = timezone.now()
        family = AdminRefreshFamily.objects.create(
            user=user,
            absolute_expires_at=now + timedelta(seconds=settings.ADMIN_REFRESH_ABSOLUTE_TTL_SECONDS),
            last_activity_at=now,
            mfa_verified_at=mfa_verified_at,
            client_ip=get_client_ip(request),
            user_agent=request.headers.get('User-Agent', '')[:255],
        )
        refresh_token, _ = self._create_refresh_token(family)
        access_token, access_session = self._issue_access(family=family, request=request)
        return AdminCredentialBundle(access_token, access_session, refresh_token, family)

    def rotate_refresh(self, *, raw_token: str, request) -> AdminCredentialBundle:
        failure = None
        bundle = None
        with transaction.atomic():
            try:
                token = self._lock_refresh_token(raw_token)
                bundle = self._rotate_locked_token(token=token, request=request, allow_locked=False)
            except AdminAuthError as error:
                failure = error
        if failure is not None:
            raise failure
        return bundle

    def unlock(self, *, raw_token: str, password: str, request) -> AdminCredentialBundle:
        failure = None
        bundle = None
        with transaction.atomic():
            try:
                token = self._lock_refresh_token(raw_token)
                now = timezone.now()
                self._validate_refresh_state(token, now=now, allow_locked=True, request=request)
                family = token.family
                unlock_failure_key = f'admin-unlock-failures:{family.pk}'
                if int(cache.get(unlock_failure_key, 0) or 0) >= settings.ADMIN_LOGIN_MAX_FAILURES:
                    raise AdminAuthError(
                        'unlock_locked',
                        'Too many failed unlock attempts. Try again later.',
                        http_status=429,
                    )
                if not family.user.check_password(password):
                    failed_attempts = int(cache.get(unlock_failure_key, 0) or 0) + 1
                    cache.set(unlock_failure_key, failed_attempts, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
                    locked_out = failed_attempts >= settings.ADMIN_LOGIN_MAX_FAILURES
                    record_security_event(
                        event_type='ADMIN_UNLOCK_LOCKED_OUT' if locked_out else 'ADMIN_UNLOCK_FAILED',
                        request=request,
                        actor=family.user,
                        severity=SecurityEvent.Severity.HIGH if locked_out else SecurityEvent.Severity.MEDIUM,
                        result='locked' if locked_out else 'invalid_password',
                        metadata={'failedAttempts': failed_attempts},
                    )
                    raise AdminAuthError(
                        'unlock_locked' if locked_out else 'invalid_credentials',
                        'Too many failed unlock attempts. Try again later.' if locked_out else 'Invalid credentials.',
                        http_status=429 if locked_out else 400,
                    )
                family.locked_at = None
                family.last_activity_at = now
                family.save(update_fields=['locked_at', 'last_activity_at', 'updated_at'])
                cache.delete(f'admin-mfa-step-up-failures:{family.pk}')
                cache.delete(unlock_failure_key)
                AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).update(
                    locked_at=None,
                    updated_at=now,
                )
                bundle = self._rotate_locked_token(token=token, request=request, allow_locked=True)
                record_security_event(
                    event_type='ADMIN_SESSION_UNLOCKED',
                    request=request,
                    actor=family.user,
                    auth_session=bundle.access_session,
                    severity=SecurityEvent.Severity.INFO,
                    result='success',
                )
            except AdminAuthError as error:
                failure = error
        if failure is not None:
            raise failure
        return bundle

    @transaction.atomic
    def lock(self, *, access_session: AuthSession, request):
        if access_session.surface != AuthSession.Surface.ADMIN or access_session.refresh_family_id is None:
            raise AdminAuthError('admin_session_required', 'A refresh-backed admin session is required.', http_status=401)
        family = AdminRefreshFamily.objects.select_for_update().get(pk=access_session.refresh_family_id)
        now = timezone.now()
        if family.status != AdminRefreshFamily.Status.ACTIVE or family.absolute_expires_at <= now:
            raise AdminAuthError('refresh_expired', 'Admin refresh session is expired or revoked.', http_status=401)
        if family.locked_at is None:
            family.locked_at = now
            family.save(update_fields=['locked_at', 'updated_at'])
            AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).update(
                locked_at=now,
                updated_at=now,
            )
            record_security_event(
                event_type='ADMIN_SESSION_LOCKED',
                request=request,
                actor=family.user,
                auth_session=access_session,
                severity=SecurityEvent.Severity.INFO,
                result='manual',
            )
        return family

    @transaction.atomic
    def revoke_family_by_cookie(self, *, raw_token: str, request):
        if not raw_token:
            return None
        token = (
            AdminRefreshToken.objects.select_for_update()
            .select_related('family__user')
            .filter(token_hash=AdminRefreshToken.build_token_hash(raw_token))
            .first()
        )
        if token is None:
            return None
        self._revoke_family(token.family, now=timezone.now())
        record_security_event(
            event_type='ADMIN_LOGOUT',
            request=request,
            actor=token.family.user,
            severity=SecurityEvent.Severity.INFO,
            result='success',
        )
        return token.family

    def authenticate_password(self, *, username: str, password: str):
        user = authenticate(username=username, password=password)
        if not user or not user.is_active or not user.can_access_admin_ui:
            return None
        return user

    def _lock_challenge(self, raw_token: str, *, expected_kind: str) -> AdminMFAChallenge:
        now = timezone.now()
        challenge = (
            AdminMFAChallenge.objects.select_for_update()
            .select_related('user')
            .filter(token_hash=AdminMFAChallenge.build_token_hash(raw_token))
            .first()
        )
        if challenge is None or challenge.kind != expected_kind or challenge.used_at is not None:
            raise AdminAuthError('mfa_challenge_invalid', 'MFA challenge is invalid or already used.', http_status=401)
        if challenge.expires_at <= now:
            challenge.used_at = now
            challenge.save(update_fields=['used_at', 'updated_at'])
            raise AdminAuthError('mfa_challenge_expired', 'MFA challenge has expired.', http_status=410)
        if not challenge.user.is_active or not challenge.user.can_access_admin_ui:
            raise AdminAuthError('mfa_challenge_invalid', 'MFA challenge is no longer valid.', http_status=401)
        return challenge

    def _record_challenge_failure(self, challenge: AdminMFAChallenge, *, request, event_type: str):
        challenge.failed_attempts += 1
        locked = challenge.failed_attempts >= settings.ADMIN_MFA_MAX_ATTEMPTS
        if locked:
            challenge.used_at = timezone.now()
        challenge.save(update_fields=['failed_attempts', 'used_at', 'updated_at'])
        record_security_event(
            event_type='ADMIN_MFA_LOCKED_OUT' if locked else event_type,
            request=request,
            actor=challenge.user,
            severity=SecurityEvent.Severity.HIGH if locked else SecurityEvent.Severity.MEDIUM,
            result='locked' if locked else 'failed',
            metadata={'failedAttempts': challenge.failed_attempts},
        )
        raise AdminAuthError(
            'mfa_challenge_locked' if locked else 'mfa_code_invalid',
            'MFA challenge is locked.' if locked else 'MFA code is invalid.',
            http_status=429 if locked else 400,
        )

    def _lock_refresh_token(self, raw_token: str) -> AdminRefreshToken:
        if not raw_token:
            raise AdminAuthError('refresh_required', 'Admin refresh cookie is required.', http_status=401)
        token = (
            AdminRefreshToken.objects.select_for_update()
            # `replaced_by` is nullable. PostgreSQL rejects FOR UPDATE across
            # the outer join that select_related('replaced_by') would create.
            # The refresh path only needs replaced_by_id, which is stored on
            # the locked token row itself.
            .select_related('family__user')
            .filter(token_hash=AdminRefreshToken.build_token_hash(raw_token))
            .first()
        )
        if token is None:
            raise AdminAuthError('refresh_invalid', 'Admin refresh token is invalid.', http_status=401)
        return token

    def _validate_refresh_state(self, token: AdminRefreshToken, *, now, allow_locked: bool, request=None):
        family = token.family
        if token.used_at is not None:
            if token.replaced_by_id and token.used_at >= now - timedelta(seconds=settings.ADMIN_REFRESH_RACE_GRACE_SECONDS):
                raise AdminAuthError('refresh_race', 'Another tab already refreshed this session.', http_status=409)
            self._revoke_family(family, now=now, reuse_detected=True)
            record_security_event(
                event_type='ADMIN_REFRESH_REUSE_DETECTED',
                request=request,
                actor=family.user,
                severity=SecurityEvent.Severity.CRITICAL,
                result='family_revoked',
                metadata={'familyId': str(family.pk)},
            )
            raise AdminAuthError('refresh_reuse_detected', 'Refresh token reuse detected.', http_status=401)
        if token.revoked_at is not None or family.status != AdminRefreshFamily.Status.ACTIVE:
            raise AdminAuthError('refresh_revoked', 'Admin refresh session is revoked.', http_status=401)
        if family.absolute_expires_at <= now:
            self._revoke_family(family, now=now)
            raise AdminAuthError('refresh_expired', 'Admin refresh session has expired.', http_status=401)
        if not family.user.is_active or not family.user.can_access_admin_ui:
            self._revoke_family(family, now=now)
            raise AdminAuthError('refresh_revoked', 'Admin access is no longer allowed.', http_status=401)
        if settings.ADMIN_MFA_REQUIRED and family.user.is_superuser and family.mfa_verified_at is None:
            self._revoke_family(family, now=now)
            raise AdminAuthError('mfa_required', 'MFA verification is required.', http_status=403)
        idle_expired = family.last_activity_at <= now - timedelta(seconds=settings.ADMIN_IDLE_LOCK_SECONDS)
        if idle_expired and family.locked_at is None:
            family.locked_at = now
            family.save(update_fields=['locked_at', 'updated_at'])
            AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).update(
                locked_at=now,
                updated_at=now,
            )
            record_security_event(
                event_type='ADMIN_SESSION_LOCKED',
                request=request,
                actor=family.user,
                severity=SecurityEvent.Severity.MEDIUM,
                result='idle',
            )
        if family.locked_at is not None and not allow_locked:
            raise AdminAuthError('session_locked', 'Admin session is locked.', http_status=423)

    def _rotate_locked_token(self, *, token: AdminRefreshToken, request, allow_locked: bool) -> AdminCredentialBundle:
        now = timezone.now()
        self._validate_refresh_state(token, now=now, allow_locked=allow_locked, request=request)
        family = token.family
        token.used_at = now
        refresh_token, replacement = self._create_refresh_token(family)
        token.replaced_by = replacement
        token.save(update_fields=['used_at', 'replaced_by', 'updated_at'])
        AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).update(
            status=AuthSession.Status.REVOKED,
            revoked_at=now,
            updated_at=now,
        )
        family.client_ip = get_client_ip(request)
        family.user_agent = request.headers.get('User-Agent', '')[:255]
        family.save(update_fields=['client_ip', 'user_agent', 'updated_at'])
        access_token, access_session = self._issue_access(family=family, request=request)
        return AdminCredentialBundle(access_token, access_session, refresh_token, family)

    def _issue_access(self, *, family: AdminRefreshFamily, request):
        return self.access_session_service_class().issue(
            user=family.user,
            request=request,
            surface=AuthSession.Surface.ADMIN,
            refresh_family=family,
            mfa_verified_at=family.mfa_verified_at,
        )

    @staticmethod
    def _create_refresh_token(family: AdminRefreshFamily):
        raw_token = token_urlsafe(48)
        token = AdminRefreshToken.objects.create(
            family=family,
            token_hash=AdminRefreshToken.build_token_hash(raw_token),
        )
        return raw_token, token

    @staticmethod
    def _revoke_family(family: AdminRefreshFamily, *, now, reuse_detected: bool = False):
        family.status = AdminRefreshFamily.Status.REVOKED
        family.revoked_at = now
        if reuse_detected:
            family.reuse_detected_at = now
        family.save(update_fields=['status', 'revoked_at', 'reuse_detected_at', 'updated_at'])
        AdminRefreshToken.objects.filter(family=family, revoked_at__isnull=True).update(revoked_at=now, updated_at=now)
        AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).update(
            status=AuthSession.Status.REVOKED,
            revoked_at=now,
            updated_at=now,
        )
