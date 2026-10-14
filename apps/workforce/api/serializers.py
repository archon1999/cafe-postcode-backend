from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from apps.users.models import User
from apps.workforce.models import AttendancePunch, CorrectionRequest, GeofenceConfig, Shift, Timesheet, WeeklyScheduleTemplate
from common.api.fields import SecureImageField


def scoped_employee(restaurant, employee_id):
    user = User.objects.filter(
        pk=employee_id, is_active=True,
        restaurant_profile__restaurant=restaurant,
        employee_profile__employment_status='active',
    ).first()
    if user is None:
        raise serializers.ValidationError({'employeeId': 'Active employee was not found in this restaurant.'})
    return user


class EmployeeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'full_name', 'username', 'phone')


class GeofenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeofenceConfig
        fields = ('workforce_enabled', 'latitude', 'longitude', 'radius_meters', 'enabled')

    def validate(self, attrs):
        instance = self.instance
        lat = attrs.get('latitude', getattr(instance, 'latitude', None))
        lon = attrs.get('longitude', getattr(instance, 'longitude', None))
        enabled = attrs.get('enabled', getattr(instance, 'enabled', False))
        if (lat is None) != (lon is None) or (enabled and lat is None):
            raise serializers.ValidationError('Enabled geofence requires both latitude and longitude.')
        if lat is not None and not -90 <= lat <= 90:
            raise serializers.ValidationError({'latitude': 'Latitude must be between -90 and 90.'})
        if lon is not None and not -180 <= lon <= 180:
            raise serializers.ValidationError({'longitude': 'Longitude must be between -180 and 180.'})
        return attrs


class WeeklyTemplateSerializer(serializers.ModelSerializer):
    employee_id = serializers.UUIDField(write_only=True)
    employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = WeeklyScheduleTemplate
        fields = ('id', 'employee_id', 'employee', 'weekday', 'start_time', 'end_time',
                  'unpaid_break_minutes', 'effective_from', 'effective_until', 'is_active')

    def validate(self, attrs):
        restaurant = self.context['restaurant']
        employee_id = attrs.pop('employee_id', None)
        if employee_id is not None:
            attrs['employee'] = scoped_employee(restaurant, employee_id)
        if self.instance is None and 'employee' not in attrs:
            raise serializers.ValidationError({'employeeId': 'Employee is required.'})
        start = attrs.get('effective_from', getattr(self.instance, 'effective_from', None))
        end = attrs.get('effective_until', getattr(self.instance, 'effective_until', None))
        if start and end and end < start:
            raise serializers.ValidationError({'effectiveUntil': 'End date must be after start date.'})
        start_time = attrs.get('start_time', getattr(self.instance, 'start_time', None))
        end_time = attrs.get('end_time', getattr(self.instance, 'end_time', None))
        if start_time and end_time:
            minutes = (
                (end_time.hour * 60 + end_time.minute) - (start_time.hour * 60 + start_time.minute)
            ) % 1440 or 1440
            break_minutes = attrs.get('unpaid_break_minutes', getattr(self.instance, 'unpaid_break_minutes', 0))
            if break_minutes >= minutes:
                raise serializers.ValidationError({'unpaidBreakMinutes': 'Break must be shorter than the shift.'})
        return attrs


class ShiftSerializer(serializers.ModelSerializer):
    employee_id = serializers.UUIDField(write_only=True)
    employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = Shift
        fields = ('id', 'employee_id', 'employee', 'starts_at', 'ends_at', 'unpaid_break_minutes',
                  'status', 'note', 'published_at', 'created_at')
        read_only_fields = ('status', 'published_at', 'created_at')

    def validate(self, attrs):
        restaurant = self.context['restaurant']
        employee_id = attrs.pop('employee_id', None)
        if employee_id is not None:
            attrs['employee'] = scoped_employee(restaurant, employee_id)
        if self.instance is None and 'employee' not in attrs:
            raise serializers.ValidationError({'employeeId': 'Employee is required.'})
        if self.instance is not None and self.instance.status != Shift.Status.DRAFT:
            raise serializers.ValidationError('Only draft shifts can be edited.')
        start = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        end = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if start and end and (end <= start or end > start + timedelta(hours=24)):
            raise serializers.ValidationError({'endsAt': 'Shift must end within 24 hours after it starts.'})
        break_minutes = attrs.get('unpaid_break_minutes', getattr(self.instance, 'unpaid_break_minutes', 0))
        if start and end and break_minutes >= int((end - start).total_seconds() // 60):
            raise serializers.ValidationError({'unpaidBreakMinutes': 'Break must be shorter than the shift.'})
        return attrs


class PunchSerializer(serializers.ModelSerializer):
    employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = AttendancePunch
        fields = ('id', 'employee', 'type', 'source', 'source_event_id', 'work_date', 'occurred_at', 'created_at',
                  'client_recorded_at', 'device_recorded_at', 'clock_skew_seconds',
                  'latitude', 'longitude', 'accuracy_meters', 'distance_meters', 'geo_status',
                  'provisional', 'requires_review', 'review_reasons', 'selfie_mime_type')


class PunchCreateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=AttendancePunch.Type.choices)
    client_event_id = serializers.RegexField(r'^[A-Za-z0-9._:-]{8,128}$')
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90, required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180, required=False)
    accuracy_meters = serializers.IntegerField(min_value=0, max_value=100000, required=False)
    client_recorded_at = serializers.DateTimeField(required=False)
    offline = serializers.BooleanField(default=False)
    selfie = SecureImageField(max_bytes=1024 * 1024, required=False, write_only=True)

    def validate(self, attrs):
        if ('latitude' in attrs) != ('longitude' in attrs):
            raise serializers.ValidationError('Both latitude and longitude are required together.')
        if attrs['offline'] and 'client_recorded_at' not in attrs:
            raise serializers.ValidationError({'clientRecordedAt': 'Offline event time is required.'})
        return attrs


class TimesheetSerializer(serializers.ModelSerializer):
    employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = Timesheet
        fields = ('id', 'employee', 'work_date', 'shift', 'period_start', 'period_end',
                  'break_minutes', 'approved_minutes', 'approved_shift_count', 'status',
                  'requires_review', 'review_reasons', 'manual_override', 'manager_note',
                  'approved_at', 'approved_by')


class TimesheetUpdateSerializer(serializers.Serializer):
    period_start = serializers.DateTimeField(required=False, allow_null=True)
    period_end = serializers.DateTimeField(required=False, allow_null=True)
    break_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    approved_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    approved_shift_count = serializers.IntegerField(min_value=0, max_value=10, required=False)
    manager_note = serializers.CharField(max_length=1000, allow_blank=False)

    def validate(self, attrs):
        start = attrs.get('period_start', self.instance.period_start)
        end = attrs.get('period_end', self.instance.period_end)
        if start and end and end <= start:
            raise serializers.ValidationError({'periodEnd': 'End must be after start.'})
        if start and end and attrs.get('approved_minutes', self.instance.approved_minutes) > (end - start).total_seconds() // 60:
            raise serializers.ValidationError({'approvedMinutes': 'Approved minutes exceed the period.'})
        return attrs


class CorrectionSerializer(serializers.ModelSerializer):
    employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = CorrectionRequest
        fields = ('id', 'employee', 'work_date', 'proposed_start_at', 'proposed_end_at', 'proposed_break_minutes',
                  'reason', 'status', 'created_at', 'reviewed_at', 'review_note')
        read_only_fields = ('status', 'created_at', 'reviewed_at', 'review_note')

    def validate(self, attrs):
        start = attrs.get('proposed_start_at')
        end = attrs.get('proposed_end_at')
        if start and end and (end <= start or end > start + timedelta(hours=24)):
            raise serializers.ValidationError({'proposedEndAt': 'End must be within 24 hours after start.'})
        if start and timezone.localtime(start).date() != attrs.get('work_date'):
            raise serializers.ValidationError({'workDate': 'Work date must match the proposed start.'})
        duration = (end - start).total_seconds() // 60 if start and end else 0
        if attrs.get('proposed_break_minutes', 0) >= duration:
            raise serializers.ValidationError({'proposedBreakMinutes': 'Break must be shorter than the shift.'})
        return attrs
