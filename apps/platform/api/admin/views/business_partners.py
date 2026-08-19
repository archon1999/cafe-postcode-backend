from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.api.admin.serializers import (
    BusinessPartnerLookupSerializer,
    PartnerActivationDefaultsSerializer,
    PartnerActivationSerializer,
    BusinessPartnerSerializer,
    PartnerActivationResultSerializer,
)
from apps.platform.api.admin.permissions import PlatformPermissionRequiredMixin
from apps.platform.helpers import get_business_partner_model
from apps.platform.selectors.business_partners import (
    filter_partners,
    generate_password,
    generate_unique_username,
    get_business_partner_role,
)
from apps.platform.services import FakturaClient, FakturaError
from apps.users.helpers import get_user_model
from common.api.admin_permissions import AdminPermissionRequiredMixin

BusinessPartner = get_business_partner_model()
User = get_user_model()


def _build_partner_activation_defaults(partner):
    password = generate_password()
    username = generate_unique_username(f'bh-{partner.inn}', exclude_user=partner.owner_user)
    return {'username': username, 'password': password}


class BusinessPartnerListCreateView(PlatformPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = BusinessPartnerSerializer

    def get_queryset(self):
        return filter_partners(
            BusinessPartner.objects.select_related('owner_user').prefetch_related('restaurants', 'extra_permissions'),
            self.request,
        )


class BusinessPartnerDetailView(PlatformPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = BusinessPartnerSerializer

    def get_queryset(self):
        return BusinessPartner.objects.select_related('owner_user').prefetch_related('restaurants', 'extra_permissions').order_by('company_name')


class BusinessPartnerLookupView(AdminPermissionRequiredMixin, APIView):
    def get(self, request):
        inn = request.query_params.get('inn', '').strip()
        if not inn:
            raise serializers.ValidationError({'inn': 'INN is required.'})

        try:
            faktura_payload = FakturaClient().lookup_company_basic_details(inn)
        except FakturaError as error:
            return Response({'detail': str(error)}, status=status.HTTP_502_BAD_GATEWAY)

        company_name = str(faktura_payload.get('CompanyName') or '').strip()
        payload = {
            'inn': str(faktura_payload.get('CompanyInn') or inn).strip(),
            'companyName': company_name,
            'legalName': company_name,
            'directorName': str(faktura_payload.get('DirectorName') or '').strip(),
            'phone': str(faktura_payload.get('PhoneNumber') or '').strip(),
            'email': str(faktura_payload.get('Email') or '').strip(),
            'address': str(faktura_payload.get('CompanyAddress') or '').strip(),
            'faktura_payload': faktura_payload,
        }
        return Response(BusinessPartnerLookupSerializer(payload).data, status=status.HTTP_200_OK)


class BusinessPartnerActivationDefaultsView(PlatformPermissionRequiredMixin, APIView):
    def get(self, request, pk):
        partner = generics.get_object_or_404(
            BusinessPartner.objects.select_related('owner_user').prefetch_related('restaurants'),
            pk=pk,
        )
        payload = _build_partner_activation_defaults(partner)
        return Response(PartnerActivationDefaultsSerializer(payload).data, status=status.HTTP_200_OK)


class BusinessPartnerActivateView(PlatformPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        partner = generics.get_object_or_404(
            BusinessPartner.objects.select_related('owner_user').prefetch_related('restaurants'),
            pk=pk,
        )
        activation_serializer = PartnerActivationSerializer(
            data=request.data,
            context={'partner': partner, 'user_model': User},
        )
        activation_serializer.is_valid(raise_exception=True)
        defaults = _build_partner_activation_defaults(partner)
        user = partner.owner_user
        username = activation_serializer.validated_data.get('username', defaults['username'])
        password = activation_serializer.validated_data.get('password', defaults['password'])

        if user is None:
            user = User.objects.create(
                username=username,
                full_name=partner.company_name,
                phone=partner.phone,
                role=get_business_partner_role(),
                is_active=True,
                is_staff=False,
            )
            partner.owner_user = user
        else:
            user.username = username
            user.role = get_business_partner_role()
            user.is_active = True
            if not user.is_superuser:
                user.is_staff = False

        user.set_password(password)
        user.save()

        partner.status = BusinessPartner.Status.ACTIVE
        partner.activated_at = timezone.now()
        partner.deactivated_at = None
        partner.save(update_fields=['owner_user', 'status', 'activated_at', 'deactivated_at', 'updated_at'])

        payload = {'partner': partner, 'username': user.username, 'password': password}
        return Response(PartnerActivationResultSerializer(payload).data, status=status.HTTP_200_OK)


class BusinessPartnerDeactivateView(PlatformPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        partner = generics.get_object_or_404(
            BusinessPartner.objects.select_related('owner_user'), pk=pk
        )
        partner.status = BusinessPartner.Status.INACTIVE
        partner.deactivated_at = timezone.now()
        partner.save(update_fields=['status', 'deactivated_at', 'updated_at'])
        if partner.owner_user_id:
            partner.owner_user.is_active = False
            partner.owner_user.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class BusinessPartnerResetPasswordView(PlatformPermissionRequiredMixin, APIView):
    def post(self, request, pk):
        partner = generics.get_object_or_404(
            BusinessPartner.objects.select_related('owner_user'), pk=pk
        )
        if partner.owner_user is None:
            raise serializers.ValidationError({'detail': 'Business partner is not activated yet.'})
        password = generate_password()
        partner.owner_user.set_password(password)
        partner.owner_user.save(update_fields=['password'])
        payload = {'partner': partner, 'username': partner.owner_user.username, 'password': password}
        return Response(PartnerActivationResultSerializer(payload).data, status=status.HTTP_200_OK)

__all__ = [
    'BusinessPartnerActivateView',
    'BusinessPartnerActivationDefaultsView',
    'BusinessPartnerDeactivateView',
    'BusinessPartnerDetailView',
    'BusinessPartnerListCreateView',
    'BusinessPartnerLookupView',
    'BusinessPartnerResetPasswordView',
]
