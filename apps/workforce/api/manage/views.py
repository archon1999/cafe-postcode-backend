from datetime import timedelta

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import EmployeeProfile, User
from apps.workforce.api.permissions import ManagerCodeRequired
from apps.workforce.api.serializers import (
    CorrectionSerializer, EmployeeSummarySerializer, GeofenceSerializer, PunchSerializer,
    ShiftSerializer, TimesheetSerializer, TimesheetUpdateSerializer, WeeklyTemplateSerializer,
)
from apps.workforce.api.staff.views import _date_range
from apps.workforce.models import AttendancePunch, CorrectionRequest, GeofenceConfig, Shift, Timesheet, WeeklyScheduleTemplate
from apps.workforce.services import approve_timesheet, generate_draft_shifts, resolve_correction


def _restaurant(request):
    return request.user.get_restaurant_scope()


def _employee_filter(request):
    employee_id = request.query_params.get('employeeId') or request.query_params.get('employee_id')
    if not employee_id:
        return {}
    employee_id = serializers.UUIDField().run_validation(employee_id)
    return {'employee_id': employee_id}


class ManagerView(APIView):
    permission_classes = [ManagerCodeRequired]
    required_code = 'workforce.view'


class TeamView(ManagerView):
    def get(self, request):
        restaurant = _restaurant(request)
        day = timezone.localdate()
        members = User.objects.filter(
            is_active=True, restaurant_profile__restaurant=restaurant,
            employee_profile__employment_status=EmployeeProfile.EmploymentStatus.ACTIVE,
        ).select_related('role').order_by('full_name')
        rows = []
        for user in members:
            shift = Shift.objects.filter(
                restaurant=restaurant, employee=user, starts_at__date=day,
                status=Shift.Status.PUBLISHED,
            ).order_by('starts_at').first()
            latest = AttendancePunch.objects.filter(
                restaurant=restaurant, employee=user,
                occurred_at__gte=timezone.now() - timedelta(hours=30),
            ).order_by('-occurred_at', '-created_at').first()
            rows.append({
                'employee': EmployeeSummarySerializer(user).data,
                'role': user.role.name if user.role_id else '',
                'shift': ShiftSerializer(shift).data if shift else None,
                'latest_punch': PunchSerializer(latest).data if latest else None,
            })
        return Response(rows)


class GeofenceView(ManagerView):
    allow_disabled_workforce = True
    method_codes = {'PUT': 'workforce.config'}

    def get(self, request):
        config, _ = GeofenceConfig.objects.get_or_create(restaurant=_restaurant(request))
        return Response(GeofenceSerializer(config).data)

    def put(self, request):
        config, _ = GeofenceConfig.objects.get_or_create(restaurant=_restaurant(request))
        serializer = GeofenceSerializer(config, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TemplateListCreateView(ManagerView):
    method_codes = {'POST': 'workforce.schedule'}

    def get(self, request):
        items = WeeklyScheduleTemplate.objects.filter(restaurant=_restaurant(request), **_employee_filter(request))
        return Response(WeeklyTemplateSerializer(items, many=True).data)

    def post(self, request):
        restaurant = _restaurant(request)
        serializer = WeeklyTemplateSerializer(data=request.data, context={'restaurant': restaurant})
        serializer.is_valid(raise_exception=True)
        item = serializer.save(restaurant=restaurant)
        return Response(WeeklyTemplateSerializer(item).data, status=status.HTTP_201_CREATED)


class TemplateDetailView(ManagerView):
    required_code = 'workforce.schedule'

    def patch(self, request, template_id):
        restaurant = _restaurant(request)
        item = get_object_or_404(WeeklyScheduleTemplate, pk=template_id, restaurant=restaurant)
        serializer = WeeklyTemplateSerializer(item, data=request.data, partial=True, context={'restaurant': restaurant})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(WeeklyTemplateSerializer(item).data)


class TemplateGenerateView(ManagerView):
    required_code = 'workforce.schedule'

    def post(self, request):
        class Input(serializers.Serializer):
            start = serializers.DateField()
            end = serializers.DateField()

        serializer = Input(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = generate_draft_shifts(restaurant=_restaurant(request), **{
            'start_date': serializer.validated_data['start'],
            'end_date': serializer.validated_data['end'],
        })
        return Response({'created': count})


class ShiftListCreateView(ManagerView):
    method_codes = {'POST': 'workforce.schedule'}

    def get(self, request):
        start, end = _date_range(request)
        shifts = Shift.objects.filter(
            restaurant=_restaurant(request), starts_at__date__gte=start, starts_at__date__lte=end,
            **_employee_filter(request),
        ).select_related('employee').order_by('starts_at')
        return Response(ShiftSerializer(shifts, many=True).data)

    def post(self, request):
        restaurant = _restaurant(request)
        serializer = ShiftSerializer(data=request.data, context={'restaurant': restaurant})
        serializer.is_valid(raise_exception=True)
        shift = serializer.save(restaurant=restaurant)
        return Response(ShiftSerializer(shift).data, status=status.HTTP_201_CREATED)


class ShiftDetailView(ManagerView):
    required_code = 'workforce.schedule'

    def patch(self, request, shift_id):
        restaurant = _restaurant(request)
        shift = get_object_or_404(Shift, pk=shift_id, restaurant=restaurant)
        if request.data.get('status') == Shift.Status.CANCELLED and shift.status == Shift.Status.PUBLISHED:
            shift.status = Shift.Status.CANCELLED
            shift.note = request.data.get('note', shift.note)
            shift.save(update_fields=['status', 'note', 'updated_at'])
            return Response(ShiftSerializer(shift).data)
        serializer = ShiftSerializer(shift, data=request.data, partial=True, context={'restaurant': restaurant})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ShiftSerializer(shift).data)


class ShiftPublishView(ManagerView):
    required_code = 'workforce.schedule'

    def post(self, request):
        class Input(serializers.Serializer):
            shift_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)

        serializer = Input(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data['shift_ids']
        if len(ids) != len(set(ids)):
            raise ValidationError({'shiftIds': 'Duplicate shift ID.'})
        restaurant = _restaurant(request)
        with transaction.atomic():
            shifts = list(Shift.objects.select_for_update().filter(restaurant=restaurant, pk__in=ids).order_by('starts_at'))
            if len(shifts) != len(ids) or any(shift.status != Shift.Status.DRAFT for shift in shifts):
                raise ValidationError({'shiftIds': 'All shifts must be draft shifts from this restaurant.'})
            # Lock each employee row so concurrent publish requests cannot both
            # pass the overlap check for the same employee.
            list(User.objects.select_for_update().filter(pk__in={item.employee_id for item in shifts}).order_by('pk'))
            for shift in shifts:
                collision = Shift.objects.filter(
                    restaurant=restaurant, employee=shift.employee, status=Shift.Status.PUBLISHED,
                    starts_at__lt=shift.ends_at, ends_at__gt=shift.starts_at,
                ).exists()
                selected_collision = any(
                    other.pk != shift.pk and other.employee_id == shift.employee_id
                    and other.starts_at < shift.ends_at and other.ends_at > shift.starts_at
                    for other in shifts
                )
                if collision or selected_collision:
                    raise ValidationError({'shiftIds': 'Employee shifts must not overlap.'})
            now = timezone.now()
            for shift in shifts:
                shift.status = Shift.Status.PUBLISHED
                shift.published_at = now
                shift.published_by = request.user
                shift.save(update_fields=['status', 'published_at', 'published_by', 'updated_at'])
        return Response(ShiftSerializer(shifts, many=True).data)


class AttendanceListView(ManagerView):
    def get(self, request):
        start, end = _date_range(request, default_days=30)
        punches = AttendancePunch.objects.filter(
            restaurant=_restaurant(request), work_date__gte=start, work_date__lte=end,
            **_employee_filter(request),
        ).select_related('employee').order_by('-occurred_at')[:1000]
        return Response(PunchSerializer(punches, many=True).data)


class PunchSelfieView(ManagerView):
    def get(self, request, punch_id):
        punch = get_object_or_404(AttendancePunch, pk=punch_id, restaurant=_restaurant(request))
        if not punch.selfie_data:
            return Response(status=status.HTTP_404_NOT_FOUND)
        response = HttpResponse(bytes(punch.selfie_data), content_type=punch.selfie_mime_type or 'image/jpeg')
        response['Cache-Control'] = 'private, no-store'
        response['Content-Disposition'] = 'inline; filename="attendance-selfie"'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class TimesheetListView(ManagerView):
    def get(self, request):
        start, end = _date_range(request, default_days=30)
        sheets = Timesheet.objects.filter(
            restaurant=_restaurant(request), work_date__gte=start, work_date__lte=end,
            **_employee_filter(request),
        ).select_related('employee').order_by('-work_date')[:1000]
        return Response(TimesheetSerializer(sheets, many=True).data)


class TimesheetDetailView(ManagerView):
    required_code = 'workforce.approve'

    def patch(self, request, timesheet_id):
        sheet = get_object_or_404(Timesheet, pk=timesheet_id, restaurant=_restaurant(request))
        if sheet.status == Timesheet.Status.APPROVED:
            raise ValidationError({'timesheet': 'Approved timesheets are locked.'})
        serializer = TimesheetUpdateSerializer(sheet, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for key, value in serializer.validated_data.items():
            setattr(sheet, key, value)
        sheet.manual_override = True
        sheet.save()
        return Response(TimesheetSerializer(sheet).data)


class TimesheetApproveView(ManagerView):
    required_code = 'workforce.approve'

    def post(self, request, timesheet_id):
        sheet = get_object_or_404(Timesheet, pk=timesheet_id, restaurant=_restaurant(request))
        note = serializers.CharField(max_length=1000, required=False, allow_blank=True).run_validation(request.data.get('note', ''))
        sheet = approve_timesheet(timesheet=sheet, manager=request.user, note=note)
        return Response(TimesheetSerializer(sheet).data)


class CorrectionListView(ManagerView):
    def get(self, request):
        queryset = CorrectionRequest.objects.filter(restaurant=_restaurant(request), **_employee_filter(request))
        state = request.query_params.get('status')
        if state:
            if state not in CorrectionRequest.Status.values:
                raise ValidationError({'status': 'Invalid correction status.'})
            queryset = queryset.filter(status=state)
        return Response(CorrectionSerializer(queryset.select_related('employee').order_by('-created_at')[:500], many=True).data)


class CorrectionResolveView(ManagerView):
    required_code = 'workforce.approve'

    def post(self, request, correction_id):
        class Input(serializers.Serializer):
            decision = serializers.ChoiceField(choices=(CorrectionRequest.Status.APPROVED, CorrectionRequest.Status.REJECTED))
            note = serializers.CharField(max_length=1000, required=False, allow_blank=True)

        serializer = Input(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = get_object_or_404(CorrectionRequest, pk=correction_id, restaurant=_restaurant(request))
        item = resolve_correction(
            correction=correction, manager=request.user,
            decision=serializer.validated_data['decision'], note=serializer.validated_data.get('note', ''),
        )
        return Response(CorrectionSerializer(item).data)
