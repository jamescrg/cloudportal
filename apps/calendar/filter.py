import django_filters
from django.db.models import Q
from django.utils import timezone
from django_filters.widgets import RangeWidget

from apps.calendar.models import Event

PERIOD_CHOICES = (
    ("upcoming", "Upcoming"),
    ("past", "Past"),
)

SORT_CHOICES = (
    ("date", "Date (Soonest)"),
    ("-date", "Date (Latest)"),
    ("description", "Description (A-Z)"),
    ("-description", "Description (Z-A)"),
    ("event_type", "Type"),
)


class EventOrderingFilter(django_filters.OrderingFilter):
    """Ordering by date keeps a day's events in time order."""

    def filter(self, qs, value):
        if value in (["date"], ["-date"]):
            sign = "-" if value[0].startswith("-") else ""
            return qs.order_by(f"{sign}date", f"{sign}start_time")
        return super().filter(qs, value)


class EventFilter(django_filters.FilterSet):
    """The calendar's filter, always for one user: only that user's events
    are filtered."""

    period = django_filters.ChoiceFilter(
        choices=PERIOD_CHOICES,
        empty_label="All",
        method="filter_period",
        label="Period",
    )
    date = django_filters.DateFromToRangeFilter(
        widget=RangeWidget(attrs={"type": "date"}),
        label="Date",
    )
    event_type = django_filters.ChoiceFilter(
        choices=Event.EVENT_TYPE_CHOICES,
        empty_label="All",
        label="Type",
    )
    order_by = EventOrderingFilter(
        fields=(
            ("date", "date"),
            ("description", "description"),
            ("event_type", "event_type"),
        ),
        empty_label=None,
    )

    class Meta:
        model = Event
        fields = ["period", "date", "event_type"]

    def __init__(self, data=None, *, user, **kwargs):
        kwargs.setdefault("queryset", Event.objects.all())
        kwargs["queryset"] = kwargs["queryset"].filter(user=user)
        super().__init__(data, **kwargs)

    def filter_period(self, queryset, name, value):
        # An event over several days is upcoming until its last day is past.
        today = timezone.localdate()
        if value == "upcoming":
            return queryset.filter(Q(date__gte=today) | Q(end_date__gte=today))
        if value == "past":
            return queryset.filter(date__lt=today).exclude(end_date__gte=today)
        return queryset
