"""Pasted quotes are read a line at a time, and the home page shows the
ones marked always and then the day's own."""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from accounts.models import CustomUser
from apps.quotes import quotes
from apps.quotes.models import Quote

pytestmark = pytest.mark.django_db

DAY = date(2030, 3, 6)


def test_parse_reads_one_quote_per_line_with_its_author():
    text = """
    Be curious. — Anon

    Simplicity -- Someone Else
    A quote with a dash - inside and no author
    Two — dashes — Last One
    Trailing dash —
    """
    assert quotes.parse(text) == [
        ("Be curious.", "Anon"),
        ("Simplicity", "Someone Else"),
        ("A quote with a dash - inside and no author", ""),
        ("Two — dashes", "Last One"),
        ("Trailing dash —", ""),
    ]


def test_add_keeps_quotes_in_order_after_the_ones_there(user):
    quotes.add(user, "First\nSecond — Two")
    quotes.add(user, "Third")
    kept = list(Quote.objects.filter(user=user))
    assert [(q.text, q.author, q.position) for q in kept] == [
        ("First", "", 0),
        ("Second", "Two", 1),
        ("Third", "", 2),
    ]


def test_serial_mode_walks_the_quotes_a_day_at_a_time(user):
    user.quotes_mode = "serial"
    user.save()
    quotes.add(user, "A\nB\nC")
    assert [q.text for q in quotes.todays(user, DAY)] == ["A"]
    # the same day again: the same quote
    assert [q.text for q in quotes.todays(user, DAY)] == ["A"]
    assert [q.text for q in quotes.todays(user, DAY + timedelta(days=1))] == ["B"]
    assert [q.text for q in quotes.todays(user, DAY + timedelta(days=2))] == ["C"]
    assert [q.text for q in quotes.todays(user, DAY + timedelta(days=3))] == ["A"]


def test_random_mode_shows_every_quote_once_before_repeating(user):
    quotes.add(user, "A\nB\nC\nD")
    shown = [quotes.todays(user, DAY + timedelta(days=i))[0].text for i in range(8)]
    assert sorted(shown[:4]) == ["A", "B", "C", "D"]
    assert shown[4:] == shown[:4]


def test_always_quotes_come_first_and_are_not_the_days_own(user):
    quotes.add(user, "Pinned — P\nA\nB")
    pinned = Quote.objects.get(text="Pinned")
    pinned.always = True
    pinned.save()
    user.quotes_mode = "serial"
    user.save()
    assert [q.text for q in quotes.todays(user, DAY)] == ["Pinned", "A"]
    assert [q.text for q in quotes.todays(user, DAY + timedelta(days=1))] == [
        "Pinned",
        "B",
    ]


def test_only_always_quotes_when_there_are_no_others(user):
    quotes.add(user, "Pinned")
    Quote.objects.filter(user=user).update(always=True)
    assert [q.text for q in quotes.todays(user, DAY)] == ["Pinned"]
    assert quotes.todays(user, DAY) == quotes.todays(user, DAY + timedelta(days=1))


def test_settings_tab_adds_marks_and_deletes(client, user):
    response = client.post(reverse("settings-quotes-add"), {"text": "One — A\nTwo"})
    assert response.status_code == 302
    one, two = Quote.objects.filter(user=user)
    assert (one.text, one.author, two.text) == ("One", "A", "Two")

    client.post(reverse("settings-quotes-always", args=[one.id]))
    one.refresh_from_db()
    assert one.always

    # from the page's checkbox, only the cell comes back
    response = client.post(
        reverse("settings-quotes-always", args=[one.id]), HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    assert 'icon-square"' in response.content.decode()
    one.refresh_from_db()
    assert not one.always

    page = client.get(reverse("settings-quotes")).content.decode()
    assert "One" in page and "Two" in page and "Random shuffle" in page

    client.get(reverse("settings-quotes-options", args=["mode", "serial"]))
    user.refresh_from_db()
    assert user.quotes_mode == "serial"

    response = client.post(
        reverse("settings-quotes-delete", args=[two.id]), HTTP_HX_REQUEST="true"
    )
    assert not Quote.objects.filter(id=two.id).exists()
    # from the page's button, the list comes back without it
    page = response.content.decode()
    assert response.status_code == 200 and "One" in page and "Two" not in page

    response = client.post(
        reverse("settings-quotes-delete", args=[one.id]), HTTP_HX_REQUEST="true"
    )
    assert "no quotes yet" in response.content.decode()
    assert (
        client.post(reverse("settings-quotes-delete", args=[one.id])).status_code == 404
    )


def test_another_users_quote_cannot_be_touched(client, user):
    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    theirs = Quote.objects.create(user=other, text="Theirs")
    assert (
        client.post(reverse("settings-quotes-always", args=[theirs.id])).status_code
        == 404
    )
    assert (
        client.post(reverse("settings-quotes-delete", args=[theirs.id])).status_code
        == 404
    )
    assert Quote.objects.filter(id=theirs.id).exists()


def test_home_page_shows_the_quotes_and_hides_without_any(client, user):
    assert "<h1>Quotes</h1>" not in client.get(reverse("home")).content.decode()
    quotes.add(user, "Pinned — P\nThe day's")
    Quote.objects.filter(text="Pinned").update(always=True)
    page = client.get(reverse("home")).content.decode()
    assert "<h1>Quotes</h1>" in page
    assert page.index("Pinned") < page.index("The day&#x27;s")
    # the close button hides it for the day
    client.get(reverse("home-toggle", args=["quotes"]))
    assert "<h1>Quotes</h1>" not in client.get(reverse("home")).content.decode()


def test_home_tab_switches_the_section_off(client, user):
    client.get(reverse("settings-home-options", args=["quotes", "disable"]))
    user.refresh_from_db()
    assert user.home_quotes == 0


def test_a_quote_can_be_edited(client, user):
    quote = Quote.objects.create(user=user, text="Draft", author="")
    page = client.get(reverse("settings-quotes-edit", args=[quote.id]))
    assert page.status_code == 200
    assert "Draft" in page.content.decode()
    response = client.post(
        reverse("settings-quotes-edit", args=[quote.id]),
        {"text": "Final", "author": "Someone", "always": "on"},
    )
    assert response.status_code == 302
    quote.refresh_from_db()
    assert (quote.text, quote.author, quote.always) == ("Final", "Someone", True)

    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    theirs = Quote.objects.create(user=other, text="Theirs")
    assert (
        client.get(reverse("settings-quotes-edit", args=[theirs.id])).status_code == 404
    )
