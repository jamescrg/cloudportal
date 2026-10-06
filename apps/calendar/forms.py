from django import forms
from django.core.exceptions import ValidationError

from apps.common.forms import ReminderFormBase

from .models import Event, EventReminder

# The longest description the column holds. The field refuses anything
# longer before clean_description runs, so the limit is stated once.
DESCRIPTION_MAX_LENGTH = Event._meta.get_field("description").max_length


class EventForm(forms.ModelForm):
    use_required_attribute = False

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
