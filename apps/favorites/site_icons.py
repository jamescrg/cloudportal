"""Site icons: the favicon of each host a favorite points at.

An icon is fetched once per host, in the background by the Django-Q
worker, and kept in the database. The home page shows it beside each
favorite, served by the icon view with a long cache life. A host whose
icon couldn't be found is tried again after a week; a found icon is
refreshed after three months.

A site that refuses the server (Cloudflare's bot wall, a load balancer
rule) gives nothing directly; for those, DuckDuckGo's icon service is
asked last. It answers a host it doesn't know with a 404, never a
placeholder, so its answer is stored like any other.
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
ICON_SERVICE = "https://icons.duckduckgo.com/ip3/{host}.ico"

# The file signatures of the image kinds a browser can show in an <img>.
# The signature names the media type an icon is stored under: servers
# label a PNG as an .ico, an .ico as a PNG, and an .ico as a plain binary
SIGNATURES = (
    (b"\x00\x00\x01\x00", "image/x-icon"),
    (b"\x89PNG", "image/png"),
    (b"GIF8", "image/gif"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
    (b"BM", "image/bmp"),
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


def image_type(data):
    """The media type an image's bytes declare, or None."""
    head = data.lstrip()
    for signature, kind in SIGNATURES:
        if head[: len(signature)] == signature:
            return kind
    return None


def _image(response):
    """The (bytes, media type) of a response that is a usable image, or
    None. The bytes decide the type; the server's header is taken only
    for an image kind without a signature here."""
    if response.status_code != 200:
        return None
    data = response.content
    if not data or len(data) > MAX_BYTES:
        return None
    kind = image_type(data)
    if kind:
        return data, kind
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    if content_type.startswith("image/"):
        return data, content_type
    return None


def fetch_icon(host):
    """Find and download a host's icon: the best one its home page
    declares, else its /favicon.ico, else what the icon service has.
    Returns (bytes, content type) or None."""
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
    candidates.append(ICON_SERVICE.format(host=host))
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


def found_hosts(hosts):
    """Of the given hosts, those with an icon on hand."""
    return set(
        SiteIcon.objects.filter(host__in=hosts, found=True).values_list(
            "host", flat=True
        )
    )


def with_hosts(favorites):
    """Give each favorite the host of its url and, in has_icon, whether
    the site's icon is on hand; a page shows a link glyph otherwise."""
    for favorite in favorites:
        favorite.host = host_of(favorite.url)
    found = found_hosts({f.host for f in favorites})
    for favorite in favorites:
        favorite.has_icon = favorite.host in found
    return favorites


def ensure(host, force=False):
    """Queue a fetch for a host that has no icon yet, or a stale one; with
    force, whatever it has."""
    if not host:
        return
    icon = SiteIcon.objects.filter(host=host).first()
    if icon and not is_due(icon) and not force:
        return
    from django_q.tasks import async_task

    async_task(fetch, host, task_name=f"site icon {host}"[:100])


def ensure_all(retry_missing=False):
    """Queue a fetch for every host of every favorite that needs one:
    with retry_missing, every host without an icon on hand, due or not.
    Returns the number queued."""
    hosts = {host_of(url) for url in Favorite.objects.values_list("url", flat=True)}
    hosts.discard("")
    have = {
        icon.host
        for icon in SiteIcon.objects.filter(host__in=hosts)
        if not is_due(icon) and (icon.found or not retry_missing)
    }
    for host in sorted(hosts - have):
        ensure(host, force=retry_missing)
    return len(hosts - have)
