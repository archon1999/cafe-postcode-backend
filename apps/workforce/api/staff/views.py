from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import EmployeeProfile
from apps.workforce.api.permissions import StaffSessionRequired
from apps.workforce.api.serializers import CorrectionSerializer, PunchCreateSerializer, PunchSerializer, ShiftSerializer, TimesheetSerializer
from apps.workforce.models import AttendancePunch, CorrectionRequest, Shift, Timesheet
from apps.workforce.services import create_pwa_punch


def _self_context(request):
    restaurant = request.user.get_restaurant_scope()
    if not EmployeeProfile.objects.filter(
        user=request.user, employment_status=EmployeeProfile.EmploymentStatus.ACTIVE,
    ).exists():
        raise PermissionDenied('An active employee profile is required.')
    return restaurant, request.user


def _date_range(request, *, default_days=14, max_days=92):
    from rest_framework import serializers

    class Params(serializers.Serializer):
        start = serializers.DateField(required=False)
        end = serializers.DateField(required=False)

    params = Params(data=request.query_params)
    params.is_valid(raise_exception=True)
    start = params.validated_data.get('start') or timezone.localdate() - timedelta(days=default_days)
    end = params.validated_data.get('end') or timezone.localdate() + timedelta(days=default_days)
    if end < start or (end - start).days > max_days:
        raise ValidationError({'end': f'Date range must be at most {max_days + 1} days.'})
    return start, end


class TodayView(APIView):
    permission_classes = [StaffSessionRequired]

    def get(self, request):
        restaurant, employee = _self_context(request)
        day = timezone.localdate()
        shift = Shift.objects.filter(
            restaurant=restaurant, employee=employee, status=Shift.Status.PUBLISHED,
            starts_at__date=day,
        ).order_by('starts_at').first()
        latest = AttendancePunch.objects.filter(
            restaurant=restaurant, employee=employee, occurred_at__gte=timezone.now() - timedelta(hours=30),
        ).order_by('-occurred_at', '-created_at').first()
        sheet = Timesheet.objects.filter(restaurant=restaurant, employee=employee, work_date=day).first()
        return Response({
            'date': day,
            'shift': ShiftSerializer(shift).data if shift else None,
            'latest_punch': PunchSerializer(latest).data if latest else None,
            'timesheet': TimesheetSerializer(sheet).data if sheet else None,
        })


class MyShiftListView(APIView):
    permission_classes = [StaffSessionRequired]

    def get(self, request):
        restaurant, employee = _self_context(request)
        start, end = _date_range(request)
        shifts = Shift.objects.filter(
            restaurant=restaurant, employee=employee, status=Shift.Status.PUBLISHED,
            starts_at__date__gte=start, starts_at__date__lte=end,
        ).order_by('starts_at')
        return Response(ShiftSerializer(shifts, many=True).data)


class MyAttendanceListView(APIView):
    permission_classes = [StaffSessionRequired]

    def get(self, request):
        restaurant, employee = _self_context(request)
        start, end = _date_range(request, default_days=30)
        punches = AttendancePunch.objects.filter(
            restaurant=restaurant, employee=employee, work_date__gte=start, work_date__lte=end,
        ).order_by('-occurred_at', '-created_at')
        return Response(PunchSerializer(punches, many=True).data)


class MyPunchView(APIView):
    permission_classes = [StaffSessionRequired]

    def post(self, request):
        restaurant, employee = _self_context(request)
        serializer = PunchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        selfie = data.get('selfie')
        selfie_data = selfie.read() if selfie else None
        selfie_mime_type = ''
        if selfie_data:
            if selfie_data.startswith(b'\xff\xd8\xff'):
                selfie_mime_type = 'image/jpeg'
            elif selfie_data.startswith(b'\x89PNG\r\n\x1a\n'):
                selfie_mime_type = 'image/png'
            elif selfie_data.startswith(b'RIFF') and selfie_data[8:12] == b'WEBP':
                selfie_mime_type = 'image/webp'
        punch, duplicate = create_pwa_punch(
            restaurant=restaurant, employee=employee,
            event_type=data['type'], source_event_id=data['client_event_id'],
            latitude=data.get('latitude'), longitude=data.get('longitude'),
            accuracy_meters=data.get('accuracy_meters'),
            client_recorded_at=data.get('client_recorded_at'), offline=data['offline'],
            selfie_data=selfie_data, selfie_mime_type=selfie_mime_type,
        )
        return Response({'punch': PunchSerializer(punch).data, 'duplicate': duplicate},
                        status=status.HTTP_200_OK if duplicate else status.HTTP_201_CREATED)


class MyPunchSelfieView(APIView):
    permission_classes = [StaffSessionRequired]

    def get(self, request, punch_id):
        restaurant, employee = _self_context(request)
        punch = get_object_or_404(AttendancePunch, pk=punch_id, restaurant=restaurant, employee=employee)
        if not punch.selfie_data:
            return Response(status=status.HTTP_404_NOT_FOUND)
        response = HttpResponse(bytes(punch.selfie_data), content_type=punch.selfie_mime_type or 'image/jpeg')
        response['Cache-Control'] = 'private, no-store'
        response['Content-Disposition'] = 'inline; filename="attendance-selfie"'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class MyCorrectionListCreateView(APIView):
    permission_classes = [StaffSessionRequired]

    def get(self, request):
        restaurant, employee = _self_context(request)
        items = CorrectionRequest.objects.filter(restaurant=restaurant, employee=employee).order_by('-created_at')[:100]
        return Response(CorrectionSerializer(items, many=True).data)

    def post(self, request):
        restaurant, employee = _self_context(request)
        serializer = CorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        work_date = serializer.validated_data['work_date']
        if Timesheet.objects.filter(
            restaurant=restaurant, employee=employee, work_date=work_date,
            status=Timesheet.Status.APPROVED,
        ).exists():
            raise ValidationError({'workDate': 'Approved timesheet is locked; ask the manager for a payroll adjustment.'})
        correction = serializer.save(restaurant=restaurant, employee=employee)
        return Response(CorrectionSerializer(correction).data, status=status.HTTP_201_CREATED)


class MyTimesheetListView(APIView):
    permission_classes = [StaffSessionRequired]

    def get(self, request):
        restaurant, employee = _self_context(request)
        start, end = _date_range(request, default_days=30)
        sheets = Timesheet.objects.filter(
            restaurant=restaurant, employee=employee, work_date__gte=start, work_date__lte=end,
        ).order_by('-work_date')
        return Response(TimesheetSerializer(sheets, many=True).data)
