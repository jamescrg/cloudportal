from django import forms
from django.core.exceptions import ValidationError

from apps.common.forms import ReminderFormBase

from .models import Event, EventReminder
from .recurrence import REPEAT_CHOICES, rule_for

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
SCOPE_CHOICES = [
    ("this", "This event"),
    ("following", "This and following events"),
]

# The longest description the column holds. The field refuses anything
# longer before clean_description runs, so the limit is stated once.
DESCRIPTION_MAX_LENGTH = Event._meta.get_field("description").max_length


class EventForm(forms.ModelForm):
    use_required_attribute = False

    # How the event repeats (see recurrence.rule_for). Not model fields: a
    # repeating event's rule lives on its EventSeries.
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
    # Only on an occurrence of a repeating event: which occurrences a save
    # (or a delete) applies to
    scope = forms.ChoiceField(
        label="Apply to",
        choices=SCOPE_CHOICES,
        initial="this",
        required=False,
        widget=forms.RadioSelect,
    )

    REPEAT_FIELDS = ("repeat", "interval", "weekdays", "ends", "until", "count")

    class Meta:
        model = Event
        fields = (
            "description",
            "date",
            "start_time",
            "end_time",
            "end_date",
            "event_type",
            "location",
        )
        labels = {
            "end_date": "End Date",
            "event_type": "Type",
        }
        widgets = {
            "description": forms.TextInput(attrs={"autofocus": True, "class": "span3"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "location": forms.TextInput(
                attrs={"class": "span2", "placeholder": "Meeting link or address"}
            ),
        }

    def __init__(self, *args, series=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.series = series
        if series is None:
            del self.fields["scope"]
        self.fields["description"].error_messages[
            "max_length"
        ] = f"Description is limited to {DESCRIPTION_MAX_LENGTH} characters."

    def clean_description(self):
        description = self.cleaned_data["description"] or ""
        if len(description) < 4:
            raise ValidationError("Description must be 4 or more characters.")
        return description

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get("date")
        end_date = cleaned_data.get("end_date")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        # An end date is only kept when it adds days: one equal to the date
        # is the same as none, and one before it is a mistake.
        if date and end_date:
            if end_date < date:
                self.add_error("end_date", "End date must be after the date.")
            elif end_date == date:
                cleaned_data["end_date"] = None

        # On one day the end must follow the start. Over several days the end
        # time is on the last day, so any clock time is after the start.
        one_day = not cleaned_data.get("end_date")
        if one_day and start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "End time must be after start time.")

        # How a repeating event ends: on a day after its first, or after a
        # number of times. Neither is kept for one that does not repeat.
        ends = cleaned_data.get("ends") or "never"
        if not cleaned_data.get("repeat"):
            ends = "never"
        until = cleaned_data.get("until") if ends == "on" else None
        count = cleaned_data.get("count") if ends == "after" else None
        if ends == "on" and not until:
            self.add_error("until", "Choose the day the event stops repeating.")
        elif ends == "on" and date and until < date:
            self.add_error("until", "The last day must be on or after the date.")
        if ends == "after" and not count:
            self.add_error("count", "Enter how many times the event happens.")
        cleaned_data["until"] = until
        cleaned_data["count"] = count
        return cleaned_data

    def rule(self):
        """The repeat rule the form asks for, or None for an event that
        does not repeat (see recurrence.rule_for)."""
        data = self.cleaned_data
        return rule_for(
            data.get("repeat"),
            data.get("interval"),
            data.get("weekdays"),
            data["date"],
            until=data.get("until"),
            count=data.get("count"),
        )


class ReminderForm(ReminderFormBase):
    """One notification for an event. A timed event counts back from its
    start; an all-day event counts back in days or weeks to a time of day."""

    class Meta(ReminderFormBase.Meta):
        model = EventReminder

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, timed=bool(event.start_time), **kwargs)
        self.event = event
