from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class DisableCSRFMiddleware(MiddlewareMixin):

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, 'DISABLE_CSRF_CHECKS', False):
            setattr(request, '_dont_enforce_csrf_checks', True)
        response = self.get_response(request)
        return response
