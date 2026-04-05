from django.db import models

from common.models import BaseModel


class EmployeeProfile(BaseModel):
    class EmploymentStatus(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'
        ARCHIVED = 'archived', 'Archived'

    class SalaryType(models.TextChoices):
        HOURLY = 'hourly', 'Hourly'
        DAILY = 'daily', 'Daily'
        MONTHLY = 'monthly', 'Monthly'

    user = models.OneToOneField('users.User', on_delete=models.CASCADE, related_name='employee_profile')
    passport_series = models.CharField(max_length=32, blank=True, default='')
    pnfl = models.CharField(max_length=32, blank=True, default='')
    birth_date = models.DateField(null=True, blank=True)
    employment_status = models.CharField(
        max_length=16,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE,
    )
    salary_type = models.CharField(max_length=16, choices=SalaryType.choices, blank=True, default='')
    base_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    kpi_percent = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ('user__username',)

    def __str__(self):
        return f'Employee profile: {self.user.username}'
