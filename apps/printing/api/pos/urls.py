from django.urls import path

from .views import PosPrintJobCreateView


urlpatterns = [path('jobs/', PosPrintJobCreateView.as_view())]
