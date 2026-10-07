from django import forms

from apps.common.forms import ReminderFormBase, RepeatFields
from apps.common.recurrence import form_initial
from config.settings import CustomFormRenderer

from .models import Task, TaskReminder


class TaskForm(RepeatFields, forms.ModelForm):
    """A task, with how it recurs (RepeatFields, counted from its due date,
    or from today for one without)."""

    default_renderer = CustomFormRenderer
    use_required_attribute = False
    repeat_start_field = "due_date"

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
            # The repeat labels ("Monthly on the second Tuesday") follow it
            "due_date": forms.DateInput(attrs={"type": "date", "x-model": "date"}),
            "due_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            return
        # An instance of a recurring task opens on its template's rule; any
        # other task's weekly repeat would start on its due date's weekday
        template = self.instance.parent_task if self.instance.pk else None
        rule = template.rule if template else None
        if rule:
            self.initial.update(form_initial(rule))
        else:
            due = self.initial.get("due_date") or self.instance.due_date
            if due:
                self.initial.setdefault("weekdays", [str(due.weekday())])

    def __iter__(self):
        # The modal lays these out itself (the repeat fields through
        # components/repeat-fields.html)
        skip = {"folder", "status", "archived", *self.REPEAT_FIELDS}
        for field in super().__iter__():
            if field.name not in skip:
                yield field


class TaskReminderForm(ReminderFormBase):
    """One notification for a task."""

    class Meta(ReminderFormBase.Meta):
        model = TaskReminder

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, timed=bool(task.due_time), **kwargs)
        self.task = task
