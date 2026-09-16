from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password


class AnalyticsModelBackend(ModelBackend):
    """Verify existing credentials without rewriting hashes via the read-only role.

    Password upgrades remain the responsibility of the normal account service.
    The default ModelBackend getter and active-user/session checks are retained.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        if username is None:
            username = kwargs.get(user_model.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = user_model._default_manager.get_by_natural_key(username)
        except user_model.DoesNotExist:
            # Same timing-hardening behavior as Django's ModelBackend.
            user_model().set_password(password)
            return None
        if check_password(password, user.password) and self.user_can_authenticate(user):
            return user
        return None
