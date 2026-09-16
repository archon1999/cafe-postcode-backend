class OAuthSecurityHeaders:
    """Keep account/consent pages out of shared caches and external frames."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/oauth/"):
            response["Cache-Control"] = "no-store"
            # no-referrer makes native form POSTs send Origin: null in browsers,
            # which correctly fails Django CSRF. strict-origin keeps the origin
            # while never exposing OAuth query parameters in Referer.
            response["Referrer-Policy"] = "strict-origin"
            response["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self'; base-uri 'none'; "
                "form-action 'self' https://chatgpt.com; frame-ancestors 'none'"
            )
        return response
