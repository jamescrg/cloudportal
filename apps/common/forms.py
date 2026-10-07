from django import forms
from django.utils import timezone

from apps.common.models import ReminderMixin
from apps.common.recurrence import REPEAT_CHOICES, pattern_for


class ReminderFormBase(forms.ModelForm):
    """One notification: an amount, a unit, and for something with no time
    of its own the time of day. ``timed`` decides which units are offered:
    something with only a day counts back in days or weeks."""

    use_required_attribute = False

    class Meta:
        fields = ("amount", "unit", "time")
        widgets = {
            "amount": forms.NumberInput(attrs={"min": 0}),
            "time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, timed, **kwargs):
        super().__init__(*args, **kwargs)
        self.all_day = not timed
        if self.all_day:
            self.fields["unit"].choices = [
                choice
                for choice in ReminderMixin.UNIT_CHOICES
                if choice[0] in ReminderMixin.ALL_DAY_UNITS
            ]
            self.initial.setdefault("amount", 1)
            self.initial.setdefault("unit", "days")
            self.initial.setdefault("time", ReminderMixin.DEFAULT_TIME)
        else:
            self.initial.setdefault("amount", 30)
            self.initial.setdefault("unit", "minutes")

    def clean(self):
        cleaned_data = super().clean()
        if self.all_day:
            if cleaned_data.get("unit") not in ReminderMixin.ALL_DAY_UNITS:
                self.add_error("unit", "With no time set, count back in days or weeks.")
            if not cleaned_data.get("time"):
                cleaned_data["time"] = ReminderMixin.DEFAULT_TIME
        else:
            cleaned_data["time"] = None
        return cleaned_data


WEEKDAY_CHOICES = [
    ("0", "Mon"),
    ("1", "Tue"),
    ("2", "Wed"),
    ("3", "Thu"),
    ("4", "Fri"),
    ("5", "Sat"),
    ("6", "Sun"),
]
ENDS_CHOICES = [("never", "Never"), ("on", "On"), ("after", "After")]


class RepeatFields(forms.Form):
    """The Repeat fields, for any form of something that can repeat (an
    event, a task): mix in ahead of the form's base, as
    ``class EventForm(RepeatFields, forms.ModelForm)``, and name the field
    holding the first day in ``repeat_start_field``. They render with
    templates/components/repeat-fields.html. Not model fields: each model
    keeps the rule in its own way (see apps.common.recurrence)."""

    REPEAT_FIELDS = ("repeat", "interval", "weekdays", "ends", "until", "count")
    repeat_start_field = "date"

    repeat = forms.ChoiceField(
        choices=REPEAT_CHOICES,
        required=False,
        widget=forms.Select(attrs={"x-model": "repeat"}),
    )
    interval = forms.IntegerField(
        label="Every",
        min_value=1,
        max_value=99,
        initial=1,
        required=False,
        widget=forms.NumberInput(attrs={"class": "repeat-interval"}),
    )
    weekdays = forms.MultipleChoiceField(
        label="On",
        choices=WEEKDAY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "repeat-weekday"}),
    )
    ends = forms.ChoiceField(
        choices=ENDS_CHOICES,
        initial="never",
        required=False,
        widget=forms.Select(attrs={"x-model": "ends"}),
    )
    until = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    count = forms.IntegerField(
        min_value=1,
        max_value=999,
        required=False,
        widget=forms.NumberInput(attrs={"class": "repeat-count"}),
    )

    def repeat_start(self):
        """The first day the rule counts from: the form's own date, or
        today for something without one (a task with no due date)."""
        return self.cleaned_data.get(self.repeat_start_field) or timezone.localdate()

    def clean(self):
        cleaned_data = super().clean()
        # How it ends: on a day on or after its first, or after a number of
        # times. Neither is kept for something that does not repeat.
        ends = cleaned_data.get("ends") or "never"
        if not cleaned_data.get("repeat"):
            ends = "never"
        until = cleaned_data.get("until") if ends == "on" else None
        count = cleaned_data.get("count") if ends == "after" else None
        start = cleaned_data.get(self.repeat_start_field)
        if ends == "on" and not until:
            self.add_error("until", "Choose the day it stops repeating.")
        elif ends == "on" and start and until < start:
            self.add_error("until", "The last day must be on or after the first.")
        if ends == "after" and not count:
            self.add_error("count", "Enter how many times it happens.")
        cleaned_data["until"] = until
        cleaned_data["count"] = count
        return cleaned_data

    def rule(self):
        """The repeat pattern the form asks for, or None for something that
        does not repeat (see apps.common.recurrence.pattern_for)."""
        data = self.cleaned_data
        return pattern_for(
            data.get("repeat"),
            data.get("interval"),
            data.get("weekdays"),
            self.repeat_start(),
            until=data.get("until"),
            count=data.get("count"),
        )
