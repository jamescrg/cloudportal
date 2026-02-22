import django_filters
from django_filters.widgets import RangeWidget

from apps.tasks.models import Task


class TasksFilter(django_filters.FilterSet):
    STATUS_CHOICES = (
        ("Pending", "Pending"),
        ("Completed", "Completed"),
    )

    status = django_filters.ChoiceFilter(
        choices=STATUS_CHOICES,
        empty_label="All",
        method="filter_status",
    )
    due_date = django_filters.DateFromToRangeFilter(
        widget=RangeWidget(attrs={"type": "date"}),
    )
    completed_date = django_filters.DateFromToRangeFilter(
        widget=RangeWidget(attrs={"type": "date"}),
    )
    created_at = django_filters.DateFromToRangeFilter(
        field_name="created_at",
        lookup_expr="date",
        widget=RangeWidget(attrs={"type": "date"}),
    )
    priority = django_filters.ChoiceFilter(
        choices=[(i, f"{i} and above") for i in range(1, 11)],
        empty_label="All",
        lookup_expr="lte",
        label="Priority",
    )
    recurring = django_filters.ChoiceFilter(
        choices=(("Yes", "Yes"), ("No", "No")),
        empty_label="All",
        method="filter_recurring",
        label="Recurring",
    )
    show_archived = django_filters.BooleanFilter(
        method="filter_archived",
        label="Show Archived",
    )

    class Meta:
        model = Task
        fields = ["status", "due_date", "completed_date", "created_at"]

    def filter_status(self, queryset, name, value):
        if value == "Pending":
            return queryset.filter(status=0)
        elif value == "Completed":
            return queryset.filter(status=1)
        return queryset

    def filter_recurring(self, queryset, name, value):
        if value == "Yes":
            return queryset.filter(parent_task__isnull=False)
        elif value == "No":
            return queryset.filter(parent_task__isnull=True)
        return queryset

    def filter_archived(self, queryset, name, value):
        if value:
            return queryset
        return queryset.filter(archived=False)
