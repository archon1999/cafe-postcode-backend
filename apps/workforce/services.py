import math
from datetime import datetime, timedelta

from django.db import IntegrityError, models, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.workforce.models import AttendancePunch, CorrectionRequest, GeofenceConfig, Shift, Timesheet, WeeklyScheduleTemplate


MAX_SHIFT_HOURS = 24


def _coordinates_status(*, restaurant, latitude, longitude, accuracy_meters):
    config = GeofenceConfig.objects.filter(restaurant=restaurant).first()
    if config is None or not config.enabled or config.latitude is None or config.longitude is None:
        return AttendancePunch.GeoStatus.UNCONFIGURED, None, ['geofence_unconfigured']
    if latitude is None or longitude is None:
        return AttendancePunch.GeoStatus.UNAVAILABLE, None, ['location_unavailable']
    phi1 = math.radians(float(config.latitude))
    phi2 = math.radians(float(latitude))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(longitude) - float(config.longitude))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    meters = round(6_371_000 * 2 * math.asin(min(1, math.sqrt(a))))
    reasons = []
    if accuracy_meters is None or accuracy_meters > 100:
        reasons.append('location_accuracy_low')
    if meters > config.radius_meters:
        reasons.append('outside_geofence')
        return AttendancePunch.GeoStatus.OUTSIDE, meters, reasons
    return AttendancePunch.GeoStatus.INSIDE, meters, reasons


def infer_work_date(*, restaurant, employee, occurred_at):
    nearby_shift = (
        Shift.objects.filter(
            restaurant=restaurant,
            employee=employee,
            status=Shift.Status.PUBLISHED,
            starts_at__lte=occurred_at + timedelta(hours=6),
            ends_at__gte=occurred_at - timedelta(hours=6),
        )
        .order_by('starts_at')
        .first()
    )
    if nearby_shift is not None:
        return timezone.localtime(nearby_shift.starts_at).date(), nearby_shift
    latest = (
        AttendancePunch.objects.filter(
            restaurant=restaurant,
            employee=employee,
            occurred_at__lte=occurred_at,
            occurred_at__gte=occurred_at - timedelta(hours=MAX_SHIFT_HOURS),
        )
        .order_by('-occurred_at', '-created_at')
        .first()
    )
    if latest and latest.type != AttendancePunch.Type.OUT:
        return latest.work_date, None
    return timezone.localtime(occurred_at).date(), None


def create_pwa_punch(*, restaurant, employee, event_type, source_event_id, latitude=None, longitude=None,
                     accuracy_meters=None, client_recorded_at=None, offline=False, selfie_data=None,
                     selfie_mime_type=''):
    now = timezone.now()
    occurred_at = client_recorded_at if offline and client_recorded_at else now
    if occurred_at < now - timedelta(hours=48) or occurred_at > now + timedelta(minutes=5):
        raise ValidationError({'clientRecordedAt': 'Offline time must be within the last 48 hours.'})
    existing = AttendancePunch.objects.filter(
        restaurant=restaurant, source=AttendancePunch.Source.PWA, source_event_id=source_event_id,
    ).first()
    if existing is not None:
        if existing.employee_id != employee.id or existing.type != event_type:
            raise ValidationError({'clientEventId': 'This event ID was already used for a different punch.'})
        return existing, True
    geo_status, distance, reasons = _coordinates_status(
        restaurant=restaurant, latitude=latitude, longitude=longitude, accuracy_meters=accuracy_meters,
    )
    if offline:
        reasons.append('offline_submission')
    work_date, _ = infer_work_date(restaurant=restaurant, employee=employee, occurred_at=occurred_at)
    previous = AttendancePunch.objects.filter(restaurant=restaurant, employee=employee).order_by('-occurred_at', '-created_at').first()
    if previous and previous.type == event_type and previous.occurred_at >= occurred_at - timedelta(hours=20):
        reasons.append('repeated_event_type')
    try:
        with transaction.atomic():
            punch = AttendancePunch.objects.create(
                restaurant=restaurant, employee=employee, work_date=work_date, type=event_type,
                source=AttendancePunch.Source.PWA, source_event_id=source_event_id,
                occurred_at=occurred_at, client_recorded_at=client_recorded_at,
                latitude=latitude, longitude=longitude, accuracy_meters=accuracy_meters,
                distance_meters=distance, geo_status=geo_status, provisional=bool(offline),
                requires_review=bool(reasons), review_reasons=reasons,
                selfie_data=selfie_data, selfie_mime_type=selfie_mime_type,
            )
            rebuild_timesheet(restaurant=restaurant, employee=employee, work_date=work_date)
            return punch, False
    except IntegrityError:
        existing = AttendancePunch.objects.get(
            restaurant=restaurant, source=AttendancePunch.Source.PWA, source_event_id=source_event_id,
        )
        if existing.employee_id != employee.id or existing.type != event_type:
            raise ValidationError({'clientEventId': 'This event ID was already used for a different punch.'})
        return existing, True


def create_device_punch(*, restaurant, employee, source_event_id, event_type, device_recorded_at,
                        device_clock_at_poll=None):
    existing = AttendancePunch.objects.filter(
        restaurant=restaurant, source=AttendancePunch.Source.HIKVISION, source_event_id=source_event_id,
    ).first()
    if existing is not None:
        if existing.employee_id != employee.id or existing.type != event_type:
            raise ValidationError({'sourceEventId': 'Event ID already belongs to another punch.'})
        return existing, True
    now = timezone.now()
    if device_recorded_at < now - timedelta(days=90) or device_recorded_at > now + timedelta(hours=24):
        raise ValidationError({'deviceRecordedAt': 'Device event is outside the 90-day backfill window.'})
    skew = int((device_clock_at_poll - now).total_seconds()) if device_clock_at_poll else None
    work_date, _ = infer_work_date(restaurant=restaurant, employee=employee, occurred_at=device_recorded_at)
    reasons = []
    if skew is None:
        reasons.append('device_clock_unverified')
    elif abs(skew) > 120:
        reasons.append('device_clock_skew')
    if now - device_recorded_at > timedelta(hours=2):
        reasons.append('delayed_import')
    if device_recorded_at > now + timedelta(minutes=5):
        reasons.append('future_device_event')
    try:
        with transaction.atomic():
            punch = AttendancePunch.objects.create(
                restaurant=restaurant, employee=employee, work_date=work_date, type=event_type,
                source=AttendancePunch.Source.HIKVISION, source_event_id=source_event_id,
                occurred_at=device_recorded_at, device_recorded_at=device_recorded_at,
                clock_skew_seconds=skew, geo_status=AttendancePunch.GeoStatus.UNCONFIGURED,
                requires_review=bool(reasons), review_reasons=reasons,
            )
            rebuild_timesheet(restaurant=restaurant, employee=employee, work_date=work_date)
            return punch, False
    except IntegrityError:
        existing = AttendancePunch.objects.get(
            restaurant=restaurant, source=AttendancePunch.Source.HIKVISION, source_event_id=source_event_id,
        )
        if existing.employee_id != employee.id or existing.type != event_type:
            raise ValidationError({'sourceEventId': 'Event ID already belongs to another punch.'})
        return existing, True


def _calculate_timesheet(punches):
    first_start = last_end = active_start = break_start = None
    total_seconds = break_seconds = complete_intervals = 0
    reasons = set()
    last_type = None
    for punch in punches:
        reasons.update(punch.review_reasons or [])
        if punch.type == AttendancePunch.Type.IN:
            if active_start is not None:
                reasons.add('duplicate_in')
            else:
                active_start = punch.occurred_at
                break_start = None
                first_start = first_start or punch.occurred_at
        elif punch.type == AttendancePunch.Type.BREAK_START:
            if active_start is None or break_start is not None:
                reasons.add('unpaired_break_start')
            else:
                break_start = punch.occurred_at
        elif punch.type == AttendancePunch.Type.BREAK_END:
            if break_start is None:
                reasons.add('unpaired_break_end')
            else:
                break_seconds += max(0, int((punch.occurred_at - break_start).total_seconds()))
                break_start = None
        elif punch.type == AttendancePunch.Type.OUT:
            if active_start is None:
                reasons.add('duplicate_out' if last_type == AttendancePunch.Type.OUT else 'unpaired_out')
            else:
                if break_start is not None:
                    break_seconds += max(0, int((punch.occurred_at - break_start).total_seconds()))
                    break_start = None
                    reasons.add('unfinished_break')
                total_seconds += max(0, int((punch.occurred_at - active_start).total_seconds()))
                complete_intervals += 1
                last_end = punch.occurred_at
                active_start = None
        last_type = punch.type
    if active_start is not None:
        reasons.add('missing_out')
    payable_minutes = max(0, (total_seconds - break_seconds) // 60)
    return first_start, last_end, break_seconds // 60, payable_minutes, complete_intervals, sorted(reasons)


def rebuild_timesheet(*, restaurant, employee, work_date):
    punches = list(AttendancePunch.objects.filter(
        restaurant=restaurant, employee=employee, work_date=work_date,
    ).order_by('occurred_at', 'created_at'))
    with transaction.atomic():
        timesheet, _ = Timesheet.objects.select_for_update().get_or_create(
            restaurant=restaurant, employee=employee, work_date=work_date,
        )
        if timesheet.status == Timesheet.Status.APPROVED or timesheet.manual_override:
            return timesheet
        start, end, break_minutes, minutes, shift_count, reasons = _calculate_timesheet(punches)
        shift = Shift.objects.filter(
            restaurant=restaurant, employee=employee, status=Shift.Status.PUBLISHED,
            starts_at__date=work_date,
        ).order_by('starts_at').first()
        if shift and shift.unpaid_break_minutes and shift_count:
            if break_minutes < shift.unpaid_break_minutes:
                minutes = max(0, minutes - (shift.unpaid_break_minutes - break_minutes))
                break_minutes = shift.unpaid_break_minutes
                reasons = sorted(set(reasons) | {'scheduled_break_unconfirmed'})
        timesheet.shift = shift
        timesheet.period_start = start
        timesheet.period_end = end
        timesheet.break_minutes = break_minutes
        timesheet.approved_minutes = minutes
        timesheet.approved_shift_count = shift_count
        timesheet.requires_review = bool(reasons)
        timesheet.review_reasons = reasons
        timesheet.save()
        return timesheet


def approve_timesheet(*, timesheet, manager, note=''):
    with transaction.atomic():
        timesheet = Timesheet.objects.select_for_update().get(pk=timesheet.pk)
        if timesheet.status == Timesheet.Status.APPROVED:
            raise ValidationError({'timesheet': 'This timesheet has already been approved.'})
        if timesheet.requires_review and not note.strip() and not timesheet.manager_note.strip():
            raise ValidationError({'note': 'A review note is required for flagged attendance.'})
        if CorrectionRequest.objects.filter(
            restaurant=timesheet.restaurant, employee=timesheet.employee,
            work_date=timesheet.work_date, status=CorrectionRequest.Status.PENDING,
        ).exists():
            raise ValidationError({'timesheet': 'Resolve pending correction requests first.'})
        if timesheet.approved_minutes <= 0 and timesheet.approved_shift_count <= 0:
            raise ValidationError({'timesheet': 'There is no work to approve.'})
        timesheet.status = Timesheet.Status.APPROVED
        timesheet.approved_by = manager
        timesheet.approved_at = timezone.now()
        if note.strip():
            timesheet.manager_note = note.strip()
        timesheet.save()
        return timesheet


def resolve_correction(*, correction, manager, decision, note=''):
    with transaction.atomic():
        correction = CorrectionRequest.objects.select_for_update().get(pk=correction.pk)
        if correction.status != CorrectionRequest.Status.PENDING:
            raise ValidationError({'correction': 'This request has already been resolved.'})
        timesheet, _ = Timesheet.objects.select_for_update().get_or_create(
            restaurant=correction.restaurant, employee=correction.employee, work_date=correction.work_date,
        )
        if decision == CorrectionRequest.Status.APPROVED:
            if timesheet.status == Timesheet.Status.APPROVED:
                raise ValidationError({'correction': 'Approved timesheets are locked; use a payroll adjustment.'})
            duration = int((correction.proposed_end_at - correction.proposed_start_at).total_seconds() // 60)
            if duration <= correction.proposed_break_minutes:
                raise ValidationError({'proposedBreakMinutes': 'Break must be shorter than the shift.'})
            timesheet.period_start = correction.proposed_start_at
            timesheet.period_end = correction.proposed_end_at
            timesheet.break_minutes = correction.proposed_break_minutes
            timesheet.approved_minutes = duration - correction.proposed_break_minutes
            timesheet.approved_shift_count = 1
            timesheet.manual_override = True
            timesheet.requires_review = True
            timesheet.review_reasons = ['approved_correction']
            timesheet.manager_note = note.strip() or correction.reason
            timesheet.save()
        correction.status = decision
        correction.reviewed_by = manager
        correction.reviewed_at = timezone.now()
        correction.review_note = note.strip()
        correction.save()
        return correction


def generate_draft_shifts(*, restaurant, start_date, end_date):
    if end_date < start_date or (end_date - start_date).days > 31:
        raise ValidationError({'end': 'Choose a date range of no more than 32 days.'})
    templates = WeeklyScheduleTemplate.objects.filter(
        restaurant=restaurant, is_active=True, effective_from__lte=end_date,
    ).filter(models.Q(effective_until__isnull=True) | models.Q(effective_until__gte=start_date))
    count = 0
    for template in templates:
        day = start_date
        while day <= end_date:
            if (day.weekday() == template.weekday and day >= template.effective_from
                    and (template.effective_until is None or day <= template.effective_until)):
                start = timezone.make_aware(datetime.combine(day, template.start_time), timezone.get_current_timezone())
                finish_date = day + timedelta(days=1) if template.end_time <= template.start_time else day
                end = timezone.make_aware(datetime.combine(finish_date, template.end_time), timezone.get_current_timezone())
                _, created = Shift.objects.get_or_create(
                    restaurant=restaurant, employee=template.employee, template=template,
                    starts_at=start, ends_at=end,
                    defaults={'unpaid_break_minutes': template.unpaid_break_minutes},
                )
                count += int(created)
            day += timedelta(days=1)
    return count
