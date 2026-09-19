from django.urls import path
from .views import AssistantRestaurantsView, BotLinkView, DraftCommitView, DraftCreateView, DraftDetailView

urlpatterns = [
    path('bot-link/', BotLinkView.as_view()),
    path('restaurants/', AssistantRestaurantsView.as_view()),
    path('drafts/', DraftCreateView.as_view()),
    path('drafts/<uuid:pk>/', DraftDetailView.as_view()),
    path('drafts/<uuid:pk>/commit/', DraftCommitView.as_view()),
]
