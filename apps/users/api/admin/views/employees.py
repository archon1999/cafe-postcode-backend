from django.conf import settings
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.api.admin.serializers import EmployeeSerializer, RoleSerializer
from apps.users.selectors.users import AdminUserQuerysetMixin, RoleListFilters, employee_role_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from apps.users.models import User
from apps.users.services.staff_auth import StaffAuthError, StaffAuthService


class EmployeeRoleListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = RoleSerializer

    def get_queryset(self):
        queryset = employee_role_queryset(self.request)
        return RoleListFilters.from_request(self.request).apply(queryset)


class EmployeeListCreateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = EmployeeSerializer
    user_surface = 'employee'

    def get_queryset(self):
        return self.get_filtered_user_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['user_surface'] = self.user_surface
        return context

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class EmployeeRetrieveUpdateView(AdminPermissionRequiredMixin, AdminUserQuerysetMixin, generics.RetrieveUpdateAPIView):
    serializer_class = EmployeeSerializer
    user_surface = 'employee'

    def get_queryset(self):
        return self.get_user_queryset()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['user_surface'] = self.user_surface
        return context


class EmployeeStaffInviteView(AdminPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        employee = User.objects.filter(pk=pk, restaurant_profile__restaurant=restaurant).first()
        if employee is None:
            return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            token, invite = StaffAuthService().create_invite(actor=request.user, employee=employee)
        except StaffAuthError as exc:
            return Response({'code': exc.code, 'detail': exc.detail}, status=exc.http_status)
        response = Response({
            'username': employee.username,
            'token': token,
            'invite_url': f'{settings.STAFF_PWA_PUBLIC_ORIGIN}/invite/{token}',
            'expires_at': invite.expires_at,
        }, status=status.HTTP_201_CREATED)
        response['Cache-Control'] = 'no-store'
        return response

__all__ = ['EmployeeListCreateView', 'EmployeeRetrieveUpdateView', 'EmployeeRoleListView']
