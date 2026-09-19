from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from .access import require_access, restaurants_for
from .drafts import commit_draft, create_draft, serialize_draft
from .inputs import normalize_input
from .models import CatalogDraft


class AssistantThrottle(UserRateThrottle):
    rate = '12/min'
    scope = 'catalog_assistant'


class AssistantView(APIView):
    # Authorization is shared with Telegram in access.py, rather than relying
    # on an HTTP-only endpoint permission that the bot cannot evaluate.
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AssistantThrottle]


class AssistantRestaurantsView(AssistantView):
    def get(self, request):
        return Response(list(restaurants_for(request.user).order_by('name').values('id', 'name')))


class BotLinkView(AssistantView):
    def post(self, request):
        from .links import issue_link
        return Response(issue_link(request.user))


class DraftCreateView(AssistantView):
    def post(self, request):
        restaurant_id = request.data.get('restaurant_id') or request.headers.get('X-Admin-Restaurant-Id')
        if not restaurant_id:
            scope = request.user.get_restaurant_scope()
            restaurant_id = scope.pk if scope else None
        require_access(request.user, restaurant_id)
        content = normalize_input(request.data.get('text'), request.FILES.getlist('files'))
        draft = create_draft(request.user, restaurant_id, content, request.data.get('category_id'))
        return Response(serialize_draft(draft), status=201)


class DraftDetailView(AssistantView):
    def get(self, request, pk):
        draft = get_object_or_404(CatalogDraft, pk=pk, owner=request.user)
        require_access(request.user, draft.restaurant_id)
        return Response(serialize_draft(draft))


class DraftCommitView(AssistantView):
    def post(self, request, pk):
        draft = commit_draft(request.user, pk, request.data.get('rows'), request.data.get('revision'))
        return Response(serialize_draft(draft))
