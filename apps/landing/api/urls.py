from django.urls import path

from apps.landing.api.views import LandingLeadView

urlpatterns = [
    path('leads/', LandingLeadView.as_view(), name='landing-leads'),
]
