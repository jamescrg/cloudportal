"""Site icons: the favicon of each host a favorite points at.

An icon is fetched once per host, in the background by the Django-Q
worker, and kept in the database. The home page shows it beside each
favorite, served by the icon view with a long cache life. A host whose
icon couldn't be found is tried again after a week; a found icon is
refreshed after three months.
"""

from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from django.utils import timezone

from apps.favorites.models import Favorite, SiteIcon

TIMEOUT = 6
MAX_BYTES = 200_000
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 CloudPortal/1.0"
    ),
    "Accept": "text/html,image/*;q=0.9,*/*;q=0.8",
}
RETRY_AFTER = timedelta(days=7)
REFRESH_AFTER = timedelta(days=90)

IMAGE_TYPES = ("image/",)
# an .ico is often served as a generic binary; these are the file signatures
# of the image kinds a browser can show in an <img>
SIGNATURES = (
    (b"\x00\x00\x01\x00", "image/x-icon"),
    (b"\x89PNG", "image/png"),
    (b"GIF8", "image/gif"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
    (b"<svg", "image/svg+xml"),
    (b"<?xml", "image/svg+xml"),
)


def host_of(url):
    """The lower-cased host of a url, or '' when it has none. A url saved
    without a scheme is read as http."""
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


class _IconLinks(HTMLParser):
    """Collects the <link rel="icon"> tags of a page's head."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        attrs = dict(attrs)
        rel = (attrs.get("rel") or "").lower().split()
        if "icon" not in rel and "apple-touch-icon" not in rel:
            return
        if attrs.get("href"):
            self.links.append(
                {
                    "href": attrs["href"],
                    "rel": rel,
                    "type": (attrs.get("type") or "").lower(),
                    "sizes": (attrs.get("sizes") or "").lower(),
                }
            )


def _score(link):
    """How well a declared icon suits a 16px slot: a proper favicon over a
    touch icon, a vector or PNG over an .ico, and a size near 32px over
    the very large or the unstated."""
    score = 0
    if "icon" in link["rel"] and "apple-touch-icon" not in link["rel"]:
        score += 4
    if "svg" in link["type"]:
        score += 3
    elif "png" in link["type"] or link["href"].lower().endswith(".png"):
        score += 2
    sizes = link["sizes"]
    if sizes == "any":
        score += 1
    elif "x" in sizes:
        try:
            width = int(sizes.split("x")[0])
        except ValueError:
            width = 0
        if 16 <= width <= 128:
            score += 1
    return score


def icon_links(html, base_url):
    """The icon urls a page declares, best first, resolved against the
    page's own url."""
    parser = _IconLinks()
    try:
        parser.feed(html)
    except Exception:
        return []
    links = sorted(parser.links, key=_score, reverse=True)
    return [urljoin(base_url, link["href"]) for link in links]


def _image(response):
    """The (bytes, content type) of a response that is a usable image, or
    None."""
    if response.status_code != 200:
        return None
    data = response.content
    if not data or len(data) > MAX_BYTES:
        return None
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    for signature, kind in SIGNATURES:
        if data.lstrip()[: len(signature)] == signature:
            return data, content_type if content_type.startswith("image/") else kind
    if content_type.startswith(IMAGE_TYPES):
        return data, content_type
    return None


def fetch_icon(host):
    """Find and download a host's icon: the best one its home page
    declares, else its /favicon.ico. Returns (bytes, content type) or
    None."""
    session = requests.Session()
    session.headers.update(HEADERS)
    candidates = []
    for scheme in ("https", "http"):
        try:
            page = session.get(f"{scheme}://{host}/", timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if page.ok and "html" in page.headers.get("Content-Type", ""):
            candidates += icon_links(page.text[:200_000], page.url)
        candidates.append(urljoin(page.url, "/favicon.ico"))
        break
    candidates.append(f"https://{host}/favicon.ico")
    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            response = session.get(url, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        image = _image(response)
        if image:
            return image
    return None


def fetch(host):
    """Fetch a host's icon and record the result, found or not. Run by
    the worker."""
    image = fetch_icon(host)
    data, content_type = image if image else (b"", "")
    SiteIcon.objects.update_or_create(
        host=host,
        defaults={
            "data": data,
            "content_type": content_type,
            "found": bool(image),
            "fetched_at": timezone.now(),
        },
    )
    return bool(image)


def is_due(icon):
    """Whether a stored icon should be fetched again."""
    age = timezone.now() - icon.fetched_at
    return age > (REFRESH_AFTER if icon.found else RETRY_AFTER)


def ensure(host):
    """Queue a fetch for a host that has no icon yet, or a stale one."""
    if not host:
        return
    icon = SiteIcon.objects.filter(host=host).first()
    if icon and not is_due(icon):
        return
    from django_q.tasks import async_task

    async_task(fetch, host, task_name=f"site icon {host}"[:100])


def ensure_all():
    """Queue a fetch for every host of every favorite that needs one.
    Returns the number queued."""
    hosts = {host_of(url) for url in Favorite.objects.values_list("url", flat=True)}
    hosts.discard("")
    have = {
        icon.host
        for icon in SiteIcon.objects.filter(host__in=hosts)
        if not is_due(icon)
    }
    for host in sorted(hosts - have):
        ensure(host)
    return len(hosts - have)
