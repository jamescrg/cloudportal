"""Change tracking for the mobile sync (apps.api.sync), which asks what
has changed since a moment: everything that changes what an app shows
moves the updated_at of the task or folder it shows it on, and whatever
someone can no longer see is recorded as a Tombstone for them.

A save, a save of some fields and a bulk update() of a task or folder
move its own updated_at (apps.common.models.TrackedTimestampMixin). The
handlers here cover what changes a row through another one:

- a notification added, changed or removed moves its task (a notification
  marked sent is a bulk update of the notification alone, and does not);
- a template whose rule changes, or which is deleted, moves its instances,
  which show the rule;
- a task folder shared or unshared moves the folder (its people) and the
  tasks in it, so someone given access receives them on their next sync
  and someone whose own task sits in a folder they have lost (taken off it,
  or leaving it) receives it again, still naming that folder, which is no
  longer in their folder_ids;
- a task folder deleted moves its tasks, which go to the Inbox;
- a user deleted moves the folders shared with them, whose people change.

And tombstones: a task deleted (one by one, in bulk, by a cascade such as a
user deleted, or as a stale recurring instance) is recorded for its owner
and the people of its folder; a task moved out of a shared folder, for
those of that folder's people who can't see it where it went; a task folder
deleted, for its owner and editors. A recurring template is never sent, so
leaves none.
"""

from datetime import timedelta

from django.db.models import Q
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone

from accounts.models import CustomUser
from apps.api.models import AppliedOp, Tombstone
from apps.folders.models import Folder
from apps.tasks.models import Task, TaskReminder
from apps.tasks.signals import tasks_moved

# How long tombstones and applied ops are kept
RETENTION = timedelta(days=90)


def folder_people(folder_id):
    """The ids of who can see a folder's tasks: its owner and editors."""
    if folder_id is None:
        return set()
    return set(
        CustomUser.objects.filter(
            Q(folder_owner__pk=folder_id) | Q(folder_editors__pk=folder_id)
        ).values_list("id", flat=True)
    )


def _touch_tasks(**filters):
    Task.objects.filter(**filters).update(updated_at=timezone.now())


@receiver(pre_delete, sender=Task)
def task_deleted(sender, instance, **kwargs):
    if instance.is_recurring:
        _touch_tasks(parent_task_id=instance.pk)
        return
    users = folder_people(instance.folder_id) | {instance.user_id}
    Tombstone.objects.create(
        kind=Tombstone.TASK, object_id=instance.pk, users=sorted(users)
    )


@receiver(tasks_moved, sender=Task)
def task_moved(sender, moved, folder_id, **kwargs):
    people = {}

    def of(fid):
        if fid not in people:
            people[fid] = folder_people(fid)
        return people[fid]

    now = timezone.now()
    lost = []
    for task_id, owner_id, left in moved:
        users = of(left) - of(folder_id) - {owner_id}
        if users:
            lost.append(
                Tombstone(
                    kind=Tombstone.TASK,
                    object_id=task_id,
                    users=sorted(users),
                    deleted_at=now,
                )
            )
    Tombstone.objects.bulk_create(lost)


@receiver(post_save, sender=Task)
def template_saved(sender, instance, raw=False, **kwargs):
    if raw or not instance.is_recurring:
        return
    if instance._rule_key() != getattr(instance, "_saved_rule", None):
        _touch_tasks(parent_task_id=instance.pk)


@receiver(post_save, sender=TaskReminder)
@receiver(post_delete, sender=TaskReminder)
def reminder_changed(sender, instance, raw=False, **kwargs):
    if not raw:
        _touch_tasks(pk=instance.task_id)


@receiver(pre_delete, sender=Folder)
def folder_deleted(sender, instance, **kwargs):
    if instance.page != "tasks":
        return
    users = folder_people(instance.pk) | {instance.user_id}
    Tombstone.objects.create(
        kind=Tombstone.FOLDER, object_id=instance.pk, users=sorted(users)
    )
    _touch_tasks(folder_id=instance.pk)


@receiver(m2m_changed, sender=Folder.editors.through)
def folder_shared(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    if reverse:
        # From the user's side (user.folder_editors.add(folder)): the
        # folders are pk_set, or all of theirs on a clear, which has
        # already happened, so they can't be told apart; none are tasks'
        # folders the site clears that way
        folder_ids = list(pk_set or [])
    else:
        folder_ids = [instance.pk]
    folders = Folder.objects.filter(pk__in=folder_ids, page="tasks")
    ids = list(folders.values_list("id", flat=True))
    if ids:
        Folder.objects.filter(pk__in=ids).update(updated_at=timezone.now())
        _touch_tasks(folder_id__in=ids)


@receiver(pre_delete, sender=CustomUser)
def user_deleted(sender, instance, **kwargs):
    # Their place on the folders shared with them goes in the cascade,
    # which sends no m2m_changed
    ids = list(
        Folder.objects.filter(editors=instance, page="tasks").values_list(
            "id", flat=True
        )
    )
    if ids:
        Folder.objects.filter(pk__in=ids).update(updated_at=timezone.now())


def prune(now=None):
    """The scheduled job: forget tombstones and applied ops older than
    RETENTION. Returns how many of each went."""
    cutoff = (now or timezone.now()) - RETENTION
    tombstones, _ = Tombstone.objects.filter(deleted_at__lt=cutoff).delete()
    ops, _ = AppliedOp.objects.filter(created_at__lt=cutoff).delete()
    return {"tombstones": tombstones, "ops": ops}
