from django import forms
from django.core.exceptions import ValidationError

from apps.common.forms import ReminderFormBase, RepeatFields

from .models import Event, EventReminder

SCOPE_CHOICES = [
    ("this", "This event"),
    ("following", "This and following events"),
]

# The longest description the column holds. The field refuses anything
# longer before clean_description runs, so the limit is stated once.
DESCRIPTION_MAX_LENGTH = Event._meta.get_field("description").max_length


class EventForm(RepeatFields, forms.ModelForm):
    """An event, with how it repeats (RepeatFields) and, on an occurrence of
    a repeating event, which occurrences a save or a delete reaches."""

    use_required_attribute = False
    repeat_start_field = "date"

    # Only on an occurrence of a repeating event: which occurrences a save
    # (or a delete) applies to
    scope = forms.ChoiceField(
        label="Apply to",
        choices=SCOPE_CHOICES,
        initial="this",
        required=False,
        # Shown in the modal's footer, beside the Delete and Save buttons it
        # governs; form= keeps it part of the form all the same
        widget=forms.RadioSelect(attrs={"x-model": "scope", "form": "event-form"}),
    )

    class Meta:
        model = Event
        fields = (
            "description",
            "date",
            "end_date",
            "start_time",
            "end_time",
            "location",
        )
        labels = {
            "end_date": "End date",
        }
        widgets = {
            "description": forms.TextInput(attrs={"autofocus": True}),
            # The repeat labels ("Monthly on the second Tuesday") follow the date
            "date": forms.DateInput(attrs={"type": "date", "x-model": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "location": forms.TextInput(
                attrs={"placeholder": "Meeting link or address"}
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

        return cleaned_data


class ReminderForm(ReminderFormBase):
    """One notification for an event. A timed event counts back from its
    start; an all-day event counts back in days or weeks to a time of day."""

    class Meta(ReminderFormBase.Meta):
        model = EventReminder

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, timed=bool(event.start_time), **kwargs)
        self.event = event
