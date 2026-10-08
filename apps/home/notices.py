"""Posting a notification to the home page, the "home" channel of
apps.common.notify: it becomes a HomeNotice, a card that stays on the
page until the user closes it (templates/home/notices.html)."""

from django.utils import timezone

from apps.home.models import HomeNotice


def _post(user, kind, title, lines, **target):
    """One card for the thing. A card still up for it (a task or event
    that moved and came due again, or yesterday's digest) is brought up to
    date and to the top rather than doubled."""
    notice = HomeNotice.objects.open_for(user).filter(kind=kind, **target).first()
    if notice is None:
        notice = HomeNotice(user=user, kind=kind, **target)
    notice.title = title
    notice.lines = "\n".join(lines)
    notice.created_at = timezone.now()
    notice.save()
    return notice


def post_task(user, task, lines):
    return _post(user, "task", task.title, lines, task=task)


def post_event(user, event, lines):
    return _post(user, "event", event.description, lines, event=event)


def post_digest(user, title, lines):
    return _post(user, "digest", title, lines)
