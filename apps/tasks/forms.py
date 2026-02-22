from django import forms

from config.settings import CustomFormRenderer

from .models import Task


class TaskForm(forms.ModelForm):
    default_renderer = CustomFormRenderer
    use_required_attribute = False

    RECURRENCE_CHOICES = [
        ("", "None"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    ]

    archived = forms.TypedChoiceField(
        choices=[(False, "No"), (True, "Yes")],
        coerce=lambda x: x == "True",
        required=False,
        label="Archived",
    )

    status = forms.TypedChoiceField(
        choices=[(0, "Pending"), (1, "Completed")],
        coerce=int,
        required=False,
        label="Status",
    )

    priority = forms.IntegerField(
        widget=forms.Select(choices=[(i, str(i)) for i in range(1, 11)]),
        initial=5,
        label="Priority",
    )

    recurrence = forms.ChoiceField(
        choices=RECURRENCE_CHOICES,
        required=False,
        label="Repeat",
    )

    class Meta:
        model = Task
        fields = (
            "folder",
            "title",
            "due_date",
            "due_time",
            "priority",
            "status",
            "archived",
        )
        widgets = {
            "title": forms.TextInput(
                attrs={"tabindex": "1", "autofocus": True, "class": "span3"}
            ),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "due_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set initial value for recurrence dropdown based on model fields
        if self.instance and self.instance.pk:
            if self.instance.is_recurring and self.instance.recurrence_type:
                self.fields["recurrence"].initial = self.instance.recurrence_type

    def __iter__(self):
        skip = {"folder", "status", "archived"}
        for field in super().__iter__():
            if field.name not in skip:
                yield field
