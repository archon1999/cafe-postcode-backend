from django.db import models

from common.models import BaseModel


class EmployeeProfile(BaseModel):
    class EmploymentStatus(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'
        ARCHIVED = 'archived', 'Archived'

    user = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='employee_profile')
    passport_series = models.CharField(max_length=32, blank=True, default='')
    pnfl = models.CharField(max_length=32, blank=True, default='')
    birth_date = models.DateField(null=True, blank=True)
    employment_status = models.CharField(
        max_length=16,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE,
    )

    class Meta:
        ordering = ('user__username',)

    def __str__(self):
        return f'Employee profile: {self.user.username}'
