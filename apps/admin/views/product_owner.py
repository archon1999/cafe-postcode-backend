from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import BusinessPartnerSerializer, PartnerActivationResultSerializer, TariffSerializer
from apps.organizations.models import BusinessPartner, Tariff

from ._business_helpers import (
    filter_partners,
    filter_tariffs,
    generate_password,
    generate_unique_username,
    get_business_partner_role,
)


class BusinessPartnerListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = BusinessPartnerSerializer

    def get_queryset(self):
        return filter_partners(BusinessPartner.objects.select_related('owner_user'), self.request)


class BusinessPartnerDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = BusinessPartnerSerializer

    def get_queryset(self):
        return BusinessPartner.objects.select_related('owner_user').order_by('company_name')


class BusinessPartnerActivateView(AdminPermissionRequiredMixin, APIView):

    def post(self, request, pk):
        partner = BusinessPartner.objects.select_related('owner_user').get(pk=pk)
        password = generate_password()
        user = partner.owner_user
        username = generate_unique_username(f'bh-{partner.inn}', exclude_user=user)

        if user is None:
            user = User.objects.create(
                username=username,
                full_name=partner.company_name,
                phone=partner.phone,
                ui_mode=User.UiMode.ADMIN,
                actor_type=User.ActorType.BUSINESS_PARTNER,
                business_partner=partner,
                role=get_business_partner_role(),
                is_active=True,
            )
            partner.owner_user = user
        else:
            user.username = username
            user.business_partner = partner
            user.role = get_business_partner_role()
            user.actor_type = User.ActorType.BUSINESS_PARTNER
            user.ui_mode = User.UiMode.ADMIN
            user.is_active = True

        user.set_password(password)
        user.save()

        partner.status = BusinessPartner.Status.ACTIVE
        partner.activated_at = timezone.now()
        partner.deactivated_at = None
        partner.save(update_fields=['owner_user', 'status', 'activated_at', 'deactivated_at', 'updated_at'])

        payload = {'partner': partner, 'username': user.username, 'password': password}
        return Response(PartnerActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class BusinessPartnerDeactivateView(AdminPermissionRequiredMixin, APIView):

    def post(self, request, pk):
        partner = BusinessPartner.objects.select_related('owner_user').get(pk=pk)
        partner.status = BusinessPartner.Status.INACTIVE
        partner.deactivated_at = timezone.now()
        partner.save(update_fields=['status', 'deactivated_at', 'updated_at'])
        if partner.owner_user_id:
            partner.owner_user.is_active = False
            partner.owner_user.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class BusinessPartnerResetPasswordView(AdminPermissionRequiredMixin, APIView):

    def post(self, request, pk):
        partner = BusinessPartner.objects.select_related('owner_user').get(pk=pk)
        if partner.owner_user is None:
            raise serializers.ValidationError({'detail': 'Business partner is not activated yet.'})
        password = generate_password()
        partner.owner_user.set_password(password)
        partner.owner_user.save(update_fields=['password'])
        payload = {'partner': partner, 'username': partner.owner_user.username, 'password': password}
        return Response(PartnerActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class TariffListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = TariffSerializer

    def get_queryset(self):
        return filter_tariffs(Tariff.objects.prefetch_related('permissions', 'allowed_roles'), self.request)


class TariffDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = TariffSerializer

    def get_queryset(self):
        return Tariff.objects.prefetch_related('permissions', 'allowed_roles').order_by('name')
