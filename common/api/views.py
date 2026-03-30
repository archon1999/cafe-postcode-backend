from django.db.models import Manager
from rest_framework import viewsets

from common.utils.language import activate_request_language, get_request_language


class TranslatedViewMixin:
    manager: Manager

    def get_queryset(self):
        self.update_lang()
        queryset = self.manager.all()
        return queryset

    def update_lang(self):
        activate_request_language(self.request)

    def get_language(self):
        return get_request_language(self.request)


class TranslatedViewSet(TranslatedViewMixin, viewsets.ReadOnlyModelViewSet):
    pass


class TranslatedModelViewSet(TranslatedViewMixin, viewsets.ModelViewSet):
    pass
