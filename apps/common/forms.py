from django import forms

from apps.common.models import ReminderMixin


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
