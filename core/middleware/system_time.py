"""Middleware to add system time to response headers."""

from common.utils.date import tashkent_now


class SystemTimeAdderMiddleware:
    """
    Middleware that adds current system time to response headers.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers['system-time'] = tashkent_now().isoformat()
        return response 
