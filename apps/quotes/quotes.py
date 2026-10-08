"""Reading pasted quotes, and choosing the day's.

A quote is one line of text. An author may follow it after an em dash,
an en dash or two hyphens ("Be curious — Anon"); the last such dash on
the line divides them, so a quote may contain dashes of its own.

The day's quote is one of the user's quotes that are not marked always.
In serial mode the quotes come round in the order they were given; in
random mode they come round in a shuffled order, so every quote shows
once before any shows twice. Either way a quote holds for the whole day,
and the next day brings the next one. A quote marked always shows every
day, before the day's own quote.
"""

import random
import re

from django.utils import timezone

from apps.quotes.models import Quote

MODES = ("random", "serial")

# A dash that gives the author, with space around it
AUTHOR_DASH = re.compile(r"\s+(?:—|–|--)\s+")


def parse(text):
    """The quotes in pasted text, as (text, author) pairs, one per
    non-empty line."""
    quotes = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        dash = None
        for match in AUTHOR_DASH.finditer(line):
            dash = match
        author = line[dash.end() :].strip() if dash else ""  # noqa: E203
        if author:
            quotes.append((line[: dash.start()].rstrip(), author))  # noqa: E203
        else:
            quotes.append((line, ""))
    return quotes


def add(user, text):
    """Keep the quotes in pasted text for a user, after the ones they
    have. Returns the quotes made."""
    last = Quote.objects.filter(user=user).order_by("-position").first()
    position = last.position + 1 if last else 0
    made = []
    for quote, author in parse(text):
        made.append(
            Quote.objects.create(
                user=user, text=quote, author=author, position=position
            )
        )
        position += 1
    return made


def _advance(user, today):
    """Move the user's place in their quotes on to the next one when the
    day has changed, and remember the day."""
    if user.quotes_cursor_date == today:
        return
    if user.quotes_cursor_date is not None:
        user.quotes_cursor += 1
    user.quotes_cursor_date = today
    user.save(update_fields=["quotes_cursor", "quotes_cursor_date"])


def todays(user, today=None):
    """The quotes the home page shows today: every quote marked always,
    then the day's own quote (none when the user has no others)."""
    today = today or timezone.localdate()
    quotes = list(Quote.objects.filter(user=user))
    always = [q for q in quotes if q.always]
    pool = [q for q in quotes if not q.always]
    if not pool:
        return always
    _advance(user, today)
    if user.quotes_mode == "random":
        # the same shuffle for the user from one day to the next, so the
        # cursor walks it: a new quote reshuffles, which is as random as
        # the mode promises
        random.Random(user.id).shuffle(pool)
    return always + [pool[user.quotes_cursor % len(pool)]]
