"""Recurring tasks.

A recurring task is a hidden template (Task.is_recurring) holding its rule
(Task.rule, the same Rule repeating events use; see apps.common.recurrence)
and what each instance is: its title, folder, priority, time and
notifications. Its instances are ordinary tasks (Task.parent_task), and
there is one open at a time: when it is done the next is made, due on the
rule's next day. The daily job (create_instances, the "recurring-tasks"
schedule) makes the next one for any template left without an open
instance, as when one was completed in bulk or deleted.

A task becomes recurring when it is given a rule (apply_edit): a template
is made from it, and the task itself stays as the first instance, keeping
its own due date and notifications.
"""

from datetime import timedelta

from django.utils import timezone

from apps.common import recurrence as rules
from apps.tasks.models import Task

# The fields a template passes to each instance
CARRIED = ("folder", "title", "priority", "due_time", "time_zone")


def open_instance(template):
    """The template's open instance, if it has one (the latest due)."""
    return (
        Task.objects.filter(parent_task=template, status=0, archived=False)
        .order_by("-due_date")
        .first()
    )


def next_due(template, after=None, today=None):
    """The day the template's next instance is due: the rule's first day
    after the last instance's due date, and never one already past. None
    once the rule has ended."""
    rule = template.rule
    if rule is None:
        return None
    today = today or timezone.localdate()
    yesterday = today - timedelta(days=1)
    after = max(after or yesterday, yesterday)
    return rules.next_after(rule, after)


def create_next(template, after=None, today=None):
    """Make the template's next instance, due on the rule's next day after
    `after` (the last instance's due date). Returns it, or None when the
    rule has ended."""
    today = today or timezone.localdate()
    due = next_due(template, after, today)
    if due is None:
        return None
    instance = Task.objects.create(
        user=template.user,
        status=0,
        due_date=due,
        parent_task=template,
        **{name: getattr(template, name) for name in CARRIED},
    )
    instance.copy_reminders_from(template)
    template.last_generated = today
    template.save(update_fields=["last_generated"])
    return instance


def after_completion(task, today=None):
    """When an instance is done, its template's next instance is made (if
    no other is open), due on the rule's next day after this one's."""
    template = task.parent_task
    if template is None or not template.is_recurring or template.archived:
        return None
    if open_instance(template):
        return None
    return create_next(template, after=task.due_date, today=today)


def create_instances(today=None):
    """The daily job: give every recurring template that has no open
    instance its next one. Returns how many were made."""
    today = today or timezone.localdate()
    made = 0
    for template in Task.objects.filter(is_recurring=True, archived=False):
        pending = Task.objects.filter(
            parent_task=template, status=0, archived=False
        ).order_by("-due_date")
        # Only one instance is open at a time; any extra are left over from
        # before, and go
        stale = list(pending.values_list("id", flat=True)[1:])
        if stale:
            Task.objects.filter(id__in=stale).delete()
        if pending.exists():
            continue
        last = (
            Task.objects.filter(parent_task=template)
            .exclude(due_date=None)
            .order_by("-due_date")
            .values_list("due_date", flat=True)
            .first()
        )
        if create_next(template, after=last, today=today):
            made += 1
    return made


def apply_edit(task, pattern, start):
    """After a task is saved from its form, bring its recurrence in step
    with what the form asked (pattern: apps.common.recurrence's pattern_for,
    or None for no repeat; start: the day the rule counts from).

    An instance passes its edit to the template (title, folder, priority,
    time, and the rule when it changed), so later instances have it; with
    the repeat removed, the template goes and the task stands alone. A task
    given a rule becomes the first instance of a new template made from it.
    """
    template = task.parent_task
    if template is not None:
        if pattern is None:
            template.delete()
            task.parent_task = None
            task.save(update_fields=["parent_task"])
            return
        for name in CARRIED:
            setattr(template, name, getattr(task, name))
        current = template.rule
        if current is None or current.pattern() != pattern:
            template.set_rule(pattern, start)
        template.save()
        return

    if pattern is None or task.is_recurring:
        return
    template = Task.objects.create(
        user=task.user,
        is_recurring=True,
        status=0,
        **{name: getattr(task, name) for name in CARRIED},
    )
    template.set_rule(pattern, start)
    template.last_generated = timezone.localdate()
    template.save()
    template.copy_reminders_from(task)
    task.parent_task = template
    task.save(update_fields=["parent_task"])
