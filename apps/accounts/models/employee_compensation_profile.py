from django.db import models

from common.models import BaseModel


class EmployeeCompensationProfile(BaseModel):
    class SalaryType(models.TextChoices):
        HOURLY = 'hourly', 'Hourly'
        DAILY = 'daily', 'Daily'
        KPI = 'kpi', 'KPI'

    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='employee_compensation_profile',
    )
    salary_type = models.CharField(max_length=16, choices=SalaryType.choices, blank=True, default='')
    base_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    kpi_percent = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ('user__username',)

    def __str__(self):
        return f'Employee compensation: {self.user.username}'
