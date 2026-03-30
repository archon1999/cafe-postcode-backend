from django.db import models

from common.models import BaseModel


class BusinessPartnerUserProfile(BaseModel):
    user = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='business_partner_profile')
    business_partner = models.ForeignKey(
        'organizations.BusinessPartner',
        on_delete=models.CASCADE,
        related_name='user_profiles',
    )

    class Meta:
        ordering = ('user__username',)

    def __str__(self):
        return f'Business partner profile: {self.user.username}'
