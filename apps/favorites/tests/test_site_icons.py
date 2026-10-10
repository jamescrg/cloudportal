"""Site icons: the host of a url, choosing an icon from a page, storing a
fetch's result, and serving it."""

from datetime import timedelta

import pytest
import requests
from django.utils import timezone

from apps.favorites import site_icons
from apps.favorites.models import Favorite, SiteIcon

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "url, host",
    [
        ("https://Docs.Djangoproject.com/en/5.2/", "docs.djangoproject.com"),
        ("www.websitesetupguide.com", "www.websitesetupguide.com"),
        ("http://localhost:8000/x", "localhost"),
        ("", ""),
        (None, ""),
        ("http://[bad", ""),
    ],
)
def test_host_of(url, host):
    assert site_icons.host_of(url) == host


def test_icon_links_prefers_a_small_png_favicon_over_a_touch_icon():
    html = """<html><head>
        <link rel="apple-touch-icon" sizes="180x180" href="/touch.png">
        <link rel="shortcut icon" href="favicon.ico">
        <link rel="icon" type="image/png" sizes="32x32" href="/icon-32.png">
        <link rel="stylesheet" href="/x.css">
    </head></html>"""
    assert site_icons.icon_links(html, "https://example.com/a/b") == [
        "https://example.com/icon-32.png",
        "https://example.com/a/favicon.ico",
        "https://example.com/touch.png",
    ]


class FakeResponse:
    def __init__(self, status=200, content=b"", content_type="", url="", text=""):
        self.status_code = status
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.url = url
        self.text = text
        self.ok = status == 200


def test_image_accepts_an_ico_served_as_a_binary():
    response = FakeResponse(
        content=b"\x00\x00\x01\x00rest", content_type="application/octet-stream"
    )
    assert site_icons._image(response) == (b"\x00\x00\x01\x00rest", "image/x-icon")


def test_image_takes_the_type_from_the_bytes_not_the_header():
    png = FakeResponse(content=b"\x89PNG....", content_type="image/x-icon")
    assert site_icons._image(png) == (b"\x89PNG....", "image/png")
    ico = FakeResponse(content=b"\x00\x00\x01\x00..", content_type="image/png")
    assert site_icons._image(ico) == (b"\x00\x00\x01\x00..", "image/x-icon")
    bmp = FakeResponse(content=b"BM6\x03", content_type="image/x-icon")
    assert site_icons._image(bmp) == (b"BM6\x03", "image/bmp")


def test_image_rejects_html_and_the_oversized():
    assert (
        site_icons._image(FakeResponse(content=b"<html>", content_type="text/html"))
        is None
    )
    big = b"\x89PNG" + b"0" * site_icons.MAX_BYTES
    assert (
        site_icons._image(FakeResponse(content=big, content_type="image/png")) is None
    )
    assert site_icons._image(FakeResponse(status=404, content=b"\x89PNG")) is None


def test_fetch_icon_takes_the_declared_icon_then_falls_back(monkeypatch):
    pages = {
        "https://example.com/": FakeResponse(
            content_type="text/html; charset=utf-8",
            url="https://example.com/",
            text='<link rel="icon" href="/i.png">',
        ),
        "https://example.com/i.png": FakeResponse(status=404),
        "https://example.com/favicon.ico": FakeResponse(
            content=b"\x00\x00\x01\x00ico", content_type="image/x-icon"
        ),
    }
    asked = []

    def get(self, url, timeout):
        asked.append(url)
        return pages.get(url, FakeResponse(status=404))

    monkeypatch.setattr(requests.Session, "get", get)
    assert site_icons.fetch_icon("example.com") == (
        b"\x00\x00\x01\x00ico",
        "image/x-icon",
    )
    assert asked == [
        "https://example.com/",
        "https://example.com/i.png",
        "https://example.com/favicon.ico",
    ]


def test_fetch_icon_asks_the_icon_service_last(monkeypatch):
    """A site that refuses the server gives nothing itself; the icon
    service is asked after every candidate of the site's own, and its 404
    for a host it doesn't know means none."""
    pages = {
        "https://icons.duckduckgo.com/ip3/walled.example.ico": FakeResponse(
            content=b"\x89PNGicon", content_type="image/png"
        ),
    }
    asked = []

    def get(self, url, timeout):
        asked.append(url)
        return pages.get(url, FakeResponse(status=403, content_type="text/html"))

    monkeypatch.setattr(requests.Session, "get", get)
    assert site_icons.fetch_icon("walled.example") == (b"\x89PNGicon", "image/png")
    assert asked[-1] == "https://icons.duckduckgo.com/ip3/walled.example.ico"
    assert asked[0] == "https://walled.example/"

    pages.clear()
    assert site_icons.fetch_icon("unknown.example") is None


def test_fetch_icon_gives_up_quietly(monkeypatch):
    def get(self, url, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests.Session, "get", get)
    assert site_icons.fetch_icon("down.example") is None


def test_fetch_records_found_and_not_found(monkeypatch):
    monkeypatch.setattr(
        site_icons, "fetch_icon", lambda host: (b"\x89PNG..", "image/png")
    )
    assert site_icons.fetch("a.example") is True
    icon = SiteIcon.objects.get(host="a.example")
    assert (bytes(icon.data), icon.content_type, icon.found) == (
        b"\x89PNG..",
        "image/png",
        True,
    )

    monkeypatch.setattr(site_icons, "fetch_icon", lambda host: None)
    assert site_icons.fetch("a.example") is False
    icon = SiteIcon.objects.get(host="a.example")
    assert (bytes(icon.data), icon.found) == (b"", False)


def test_is_due():
    now = timezone.now()
    assert not site_icons.is_due(
        SiteIcon(found=True, fetched_at=now - timedelta(days=89))
    )
    assert site_icons.is_due(SiteIcon(found=True, fetched_at=now - timedelta(days=91)))
    assert not site_icons.is_due(
        SiteIcon(found=False, fetched_at=now - timedelta(days=6))
    )
    assert site_icons.is_due(SiteIcon(found=False, fetched_at=now - timedelta(days=8)))


@pytest.fixture
def queued(monkeypatch):
    """The hosts whose fetch was queued on the worker."""
    hosts = []
    import django_q.tasks

    monkeypatch.setattr(
        django_q.tasks, "async_task", lambda func, host, **kw: hosts.append(host)
    )
    return hosts


def test_saving_a_favorite_queues_its_hosts_icon(user, folder1, queued):
    Favorite.objects.create(
        user=user, folder=folder1, name="A", url="https://a.example/x"
    )
    assert queued == ["a.example"]
    # a host with a fresh icon isn't fetched again
    SiteIcon.objects.create(host="b.example", found=True, fetched_at=timezone.now())
    Favorite.objects.create(
        user=user, folder=folder1, name="B", url="https://b.example/"
    )
    assert queued == ["a.example"]
    # nor one with no url
    Favorite.objects.create(user=user, folder=folder1, name="C", url="")
    assert queued == ["a.example"]


def test_ensure_all_queues_each_missing_host_once(user, folder1, queued):
    for url in ("https://a.example/1", "https://a.example/2", "https://b.example/"):
        Favorite.objects.create(user=user, folder=folder1, name="x", url=url)
    queued.clear()
    SiteIcon.objects.create(host="b.example", found=True, fetched_at=timezone.now())
    assert site_icons.ensure_all() == 1
    assert queued == ["a.example"]


def test_ensure_all_can_retry_the_hosts_without_an_icon(user, folder1, queued):
    for url in ("https://a.example/", "https://b.example/", "https://c.example/"):
        Favorite.objects.create(user=user, folder=folder1, name="x", url=url)
    queued.clear()
    now = timezone.now()
    SiteIcon.objects.create(host="a.example", found=True, fetched_at=now)
    SiteIcon.objects.create(host="b.example", found=False, fetched_at=now)
    SiteIcon.objects.create(
        host="c.example", found=False, fetched_at=now - timedelta(days=8)
    )
    # the nightly pass takes only the host whose miss is a week old
    assert site_icons.ensure_all() == 1
    assert queued == ["c.example"]
    queued.clear()
    # a retry takes every host without an icon, and leaves the found one
    assert site_icons.ensure_all(retry_missing=True) == 2
    assert queued == ["b.example", "c.example"]


def test_icon_view_serves_the_icon_or_the_globe(client, user):
    SiteIcon.objects.create(
        host="a.example",
        data=b"\x89PNG..",
        content_type="image/png",
        found=True,
        fetched_at=timezone.now(),
    )
    response = client.get("/favorites/icons/A.example")
    assert response.status_code == 200
    assert response.content == b"\x89PNG.."
    assert response["Content-Type"] == "image/png"
    assert "max-age=604800" in response["Cache-Control"]

    response = client.get("/favorites/icons/nobody.example")
    assert response["Content-Type"] == "image/svg+xml"
    assert b"<svg" in response.content
    assert "max-age=3600" in response["Cache-Control"]


def test_home_page_shows_the_icon_on_hand_or_a_link_glyph(client, user, folder1):
    folder1.home_column = 1
    folder1.home_rank = 1
    folder1.save()
    Favorite.objects.create(
        user=user,
        folder=folder1,
        name="Docs",
        url="https://docs.example/a",
        home_rank=1,
    )
    Favorite.objects.create(
        user=user, folder=folder1, name="New", url="https://new.example/", home_rank=2
    )
    SiteIcon.objects.create(
        host="docs.example",
        data=b"\x89PNG",
        content_type="image/png",
        found=True,
        fetched_at=timezone.now(),
    )
    SiteIcon.objects.create(host="new.example", found=False, fetched_at=timezone.now())
    html = client.get("/home/").content.decode()
    assert 'src="/favorites/icons/docs.example"' in html
    assert "/favorites/icons/new.example" not in html
    assert html.count("favicon-none icon-link") == 1


def test_home_page_icons_can_be_off_or_in_their_own_colours(client, user, folder1):
    folder1.home_column = 1
    folder1.home_rank = 1
    folder1.save()
    Favorite.objects.create(
        user=user,
        folder=folder1,
        name="Docs",
        url="https://docs.example/a",
        home_rank=1,
    )
    html = client.get("/home/").content.decode()
    assert "favicons-muted" in html and "favicon" in html.split("home-board")[1]

    user.home_icons_muted = 0
    user.save()
    html = client.get("/home/").content.decode()
    assert "favicons-muted" not in html

    user.home_icons = 0
    user.save()
    html = client.get("/home/").content.decode()
    assert 'class="favicon' not in html
    assert "/favorites/icons/" not in html


def test_favorites_page_carries_the_icons_too(client, user, folder1):
    user.favorites_folder = folder1.id
    user.save()
    Favorite.objects.create(
        user=user, folder=folder1, name="Docs", url="https://docs.example/a"
    )
    SiteIcon.objects.create(
        host="docs.example",
        data=b"\x89PNG",
        content_type="image/png",
        found=True,
        fetched_at=timezone.now(),
    )
    html = client.get("/favorites/").content.decode()
    assert 'src="/favorites/icons/docs.example"' in html
    assert "favicons-muted" in html
    user.home_icons = 0
    user.save()
    assert "/favorites/icons/" not in client.get("/favorites/").content.decode()
