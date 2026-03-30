from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

DEFAULT_DATE_FORMAT = '%Y-%m-%d'
DEFAULT_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
TASHKENT_TIMEZONE = ZoneInfo('Asia/Tashkent')

SECONDS_PER_MINUTE = timedelta(minutes=1).total_seconds()
SECONDS_PER_HOUR = timedelta(hours=1).total_seconds()


def as_edate(value: date | datetime) -> 'EDate':
    if isinstance(value, datetime):
        value = value.date()
    return EDate(value.year, value.month, value.day)


def as_edatetime(value: datetime) -> 'EDateTime':
    return EDateTime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
        tzinfo=value.tzinfo,
        fold=value.fold,
    )


def localize_to_tashkent(value: datetime | None = None) -> 'EDateTime':
    current_value = value or timezone.now()
    if timezone.is_naive(current_value):
        current_value = timezone.make_aware(current_value, TASHKENT_TIMEZONE)
    return as_edatetime(current_value.astimezone(TASHKENT_TIMEZONE))


def tashkent_now() -> 'EDateTime':
    return localize_to_tashkent()


def tashkent_today() -> 'EDate':
    return as_edate(tashkent_now())


def tashkent_day_bounds(value: date | datetime | None = None) -> tuple['EDateTime', 'EDateTime']:
    target_date = tashkent_today() if value is None else as_edate(value)
    start = target_date.to_datetime(tzinfo=TASHKENT_TIMEZONE)
    end = as_edatetime(start + timedelta(days=1))
    return start, end


def tashkent_month_bounds(year: int, month: int) -> tuple['EDateTime', 'EDateTime']:
    start = as_edatetime(datetime(year, month, 1, tzinfo=TASHKENT_TIMEZONE))
    if month == 12:
        end = as_edatetime(datetime(year + 1, 1, 1, tzinfo=TASHKENT_TIMEZONE))
    else:
        end = as_edatetime(datetime(year, month + 1, 1, tzinfo=TASHKENT_TIMEZONE))
    return start, end


def tashkent_year_bounds(year: int) -> tuple['EDateTime', 'EDateTime']:
    start = as_edatetime(datetime(year, 1, 1, tzinfo=TASHKENT_TIMEZONE))
    end = as_edatetime(datetime(year + 1, 1, 1, tzinfo=TASHKENT_TIMEZONE))
    return start, end


class EDate(date):
    def to_datetime(self, *, tzinfo=None) -> 'EDateTime':
        return as_edatetime(datetime(self.year, self.month, self.day, tzinfo=tzinfo))

    def tomorrow(self) -> 'EDate':
        return as_edate(self.to_datetime() + timedelta(days=1))

    def yesterday(self) -> 'EDate':
        return as_edate(self.to_datetime() - timedelta(days=1))

    def start_of_month(self) -> 'EDate':
        return self.replace(day=1)

    def start_of_year(self) -> 'EDate':
        return self.replace(day=1, month=1)

    def end_of_month(self) -> 'EDate':
        _, day_count = monthrange(self.year, self.month)
        return self.replace(day=day_count)

    def end_of_year(self) -> 'EDate':
        return self.replace(day=31, month=12)

    def start_of_previous_month(self) -> 'EDate':
        return self.start_of_month().yesterday().start_of_month()

    def start_of_previous_year(self) -> 'EDate':
        return self.replace(day=1, month=1, year=self.year - 1)

    def end_of_previous_month(self) -> 'EDate':
        return self.start_of_month().yesterday()

    def end_of_previous_year(self) -> 'EDate':
        return self.replace(day=31, month=12, year=self.year - 1)

    def strftime(self, __format=DEFAULT_DATE_FORMAT):
        return super().strftime(__format)

    @staticmethod
    def strptime(__date_string: str, __format=DEFAULT_DATE_FORMAT) -> 'EDate':
        return as_edate(datetime.strptime(__date_string, __format))

    def __str__(self):
        return self.strftime()


class EDateTime(datetime):
    def start_of_minute(self) -> 'EDateTime':
        return as_edatetime(self.replace(second=0, microsecond=0))

    def end_of_minute(self) -> 'EDateTime':
        return as_edatetime(self.replace(second=59, microsecond=999999))

    def start_of_hour(self) -> 'EDateTime':
        return as_edatetime(self.start_of_minute().replace(minute=0))

    def end_of_hour(self) -> 'EDateTime':
        return as_edatetime(self.end_of_minute().replace(minute=59))

    def start_of_day(self) -> 'EDateTime':
        return as_edatetime(self.start_of_hour().replace(hour=0))

    def end_of_day(self) -> 'EDateTime':
        return as_edatetime(self.end_of_hour().replace(hour=23))

    def next_hour(self) -> 'EDateTime':
        return as_edatetime(self + timedelta(hours=1))

    def previous_hour(self) -> 'EDateTime':
        return as_edatetime(self - timedelta(hours=1))

    def tomorrow(self) -> 'EDateTime':
        return as_edatetime(self + timedelta(days=1))

    def yesterday(self) -> 'EDateTime':
        return as_edatetime(self - timedelta(days=1))

    def start_of_month(self) -> 'EDateTime':
        return as_edatetime(self.replace(day=1))

    def end_of_month(self) -> 'EDateTime':
        _, day_count = monthrange(self.year, self.month)
        return as_edatetime(self.replace(day=day_count))

    def start_of_year(self) -> 'EDateTime':
        return as_edatetime(self.replace(day=1, month=1))

    def end_of_year(self) -> 'EDateTime':
        return as_edatetime(self.replace(day=31, month=12))

    def start_of_previous_month(self) -> 'EDateTime':
        return as_edatetime(self.start_of_month().yesterday().replace(day=1))

    def end_of_previous_month(self) -> 'EDateTime':
        return as_edatetime(self.start_of_month().yesterday())

    def start_of_previous_year(self) -> 'EDateTime':
        return as_edatetime(self.replace(day=1, month=1, year=self.year - 1))

    def end_of_previous_year(self) -> 'EDateTime':
        return as_edatetime(self.replace(day=31, month=12, year=self.year - 1))

    def strftime(self, __format=DEFAULT_DATETIME_FORMAT):
        return super().strftime(__format)

    @staticmethod
    def strptime(__date_string: str, __format=DEFAULT_DATETIME_FORMAT) -> 'EDateTime':
        return as_edatetime(datetime.strptime(__date_string, __format))

    def __str__(self):
        return self.strftime()


def generate_months():
    for month_number in range(1, 13):
        yield month_number
