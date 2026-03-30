from common.utils.language import activate_request_language


class RequestLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        activate_request_language(request)
        return self.get_response(request)
