from django.urls import path

from apps.devices import admin_control_views as views


urlpatterns = [
    path('branches/', views.AdminControlBranchListView.as_view()),
    path('branches/<uuid:restaurant_id>/devices/', views.AdminControlBranchDeviceListView.as_view()),
    path('branches/<uuid:restaurant_id>/devices/<uuid:device_id>/revoke/', views.AdminControlDeviceRevokeView.as_view()),
    path('pairings/resolve/', views.AdminControlPairingResolveView.as_view()),
    path('branches/<uuid:restaurant_id>/pairings/<uuid:pairing_id>/approve/', views.AdminControlPairingApproveView.as_view()),
    path('branches/<uuid:restaurant_id>/pairings/<uuid:pairing_id>/reject/', views.AdminControlPairingRejectView.as_view()),
    path('branches/<uuid:restaurant_id>/telegram-subscriptions/', views.AdminControlTelegramSubscriptionListView.as_view()),
    path('branches/<uuid:restaurant_id>/telegram-link/', views.AdminControlTelegramLinkIssueView.as_view()),
    path(
        'branches/<uuid:restaurant_id>/telegram-subscriptions/<uuid:subscription_id>/revoke/',
        views.AdminControlTelegramSubscriptionRevokeView.as_view(),
    ),
]
