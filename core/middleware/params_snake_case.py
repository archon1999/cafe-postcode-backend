import re
from django.http import QueryDict


def _camel_to_snake(name: str) -> str:
    """Convert lowerCamelCase or CamelCase to snake_case."""
    return re.sub(r'(?<!^)([A-Z])', r'_\1', name).lower()


class ParamsSnakeCaseMiddleware:
    """Convert incoming query parameters to snake_case for consistent usage."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api'):
            request.GET = self._convert_querydict(request.GET)
            request.POST = self._convert_querydict(request.POST)
        return self.get_response(request)

    @staticmethod
    def _convert_querydict(querydict: QueryDict) -> QueryDict:
        """Return a new QueryDict with keys converted to snake_case."""
        mutable_copy = QueryDict('', mutable=True)
        for key, values in querydict.lists():
            mutable_copy.setlist(_camel_to_snake(key), values)
        mutable_copy._mutable = False
        return mutable_copy
