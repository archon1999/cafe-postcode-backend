from django.utils import timezone

from common.utils.date import TASHKENT_TIMEZONE


class ActivateTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.activate(TASHKENT_TIMEZONE)
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
