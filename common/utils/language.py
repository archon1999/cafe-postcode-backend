from django.utils import translation


SUPPORTED_API_LANGUAGES = {'uz', 'uz-crl', 'ru'}


def normalize_language_code(value: str | None, default: str = 'uz') -> str:
    candidate = (value or '').strip()
    if not candidate:
        return default

    candidate = candidate.replace('_', '-')
    normalized = candidate.split(',', 1)[0].split(';', 1)[0].strip().lower()

    if normalized in SUPPORTED_API_LANGUAGES:
        return normalized

    short_normalized = normalized[:2]
    if short_normalized in SUPPORTED_API_LANGUAGES:
        return short_normalized

    return default


def get_request_language(request, default: str = 'uz') -> str:
    if request is None:
        return default

    query_params = getattr(request, 'query_params', None) or getattr(request, 'GET', None) or {}
    headers = getattr(request, 'headers', None) or {}
    cookies = getattr(request, 'COOKIES', None) or {}

    return normalize_language_code(
        query_params.get('lang')
        or query_params.get('django_language')
        or headers.get('django-language')
        or headers.get('x-language')
        or headers.get('accept-language')
        or cookies.get('django_language')
        or getattr(request, 'LANGUAGE_CODE', None)
        or getattr(request, 'LANGUAGE', None),
        default=default,
    )


def activate_request_language(request, default: str = 'uz') -> str:
    language = get_request_language(request, default=default)
    translation.activate(language)
    request.LANGUAGE_CODE = language
    request.LANGUAGE = language
    return language
