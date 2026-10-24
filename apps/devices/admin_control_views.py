"""Admin-shell adapters for the existing device-control workflows.

The Control PWA keeps its existing operator audience. The admin workspace is
restricted to superusers and requires recent MFA for changes when MFA is on.
Pairing validation, device allowlists, audit events and scope checks remain in
the shared Control views/services rather than a second implementation.
"""

from uuid import UUID

from rest_framework import permissions
from rest_framework.exceptions import ValidationError

from apps.devices import control_views
from apps.devices.permissions import IsSuperuser
from common.api.admin_permissions import RecentAdminMFAPermission
from common.api.permissions import EndpointRBACPermission


ADMIN_CONTROL_READ_PERMISSIONS = [permissions.IsAuthenticated, EndpointRBACPermission, IsSuperuser]
ADMIN_CONTROL_WRITE_PERMISSIONS = [*ADMIN_CONTROL_READ_PERMISSIONS, RecentAdminMFAPermission]


class AdminControlBranchListView(control_views.ControlBranchListView):
    permission_classes = ADMIN_CONTROL_READ_PERMISSIONS

    def get_queryset(self):
        queryset = super().get_queryset()
        partner_id = self.request.query_params.get('business_partner_id')
        if not partner_id:
            return queryset
        try:
            partner_id = UUID(str(partner_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValidationError({'business_partner_id': 'Invalid business partner.'}) from error
        return queryset.filter(business_partner_id=partner_id)


class AdminControlBranchDeviceListView(control_views.ControlBranchDeviceListView):
    permission_classes = ADMIN_CONTROL_READ_PERMISSIONS


class AdminControlPairingResolveView(control_views.ControlPairingResolveView):
    permission_classes = ADMIN_CONTROL_READ_PERMISSIONS


class AdminControlPairingApproveView(control_views.ControlPairingApproveView):
    permission_classes = ADMIN_CONTROL_WRITE_PERMISSIONS


class AdminControlPairingRejectView(control_views.ControlPairingRejectView):
    permission_classes = ADMIN_CONTROL_WRITE_PERMISSIONS


class AdminControlDeviceRevokeView(control_views.ControlDeviceRevokeView):
    permission_classes = ADMIN_CONTROL_WRITE_PERMISSIONS


class AdminControlTelegramSubscriptionListView(control_views.ControlTelegramSubscriptionListView):
    permission_classes = ADMIN_CONTROL_READ_PERMISSIONS


class AdminControlTelegramLinkIssueView(control_views.ControlTelegramLinkIssueView):
    permission_classes = ADMIN_CONTROL_WRITE_PERMISSIONS


class AdminControlTelegramSubscriptionRevokeView(control_views.ControlTelegramSubscriptionRevokeView):
    permission_classes = ADMIN_CONTROL_WRITE_PERMISSIONS
