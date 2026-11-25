"""Claude's connector: the MCP endpoint, and the user's list of what is
connected (Settings → Connected apps)."""

import json
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.models import AccessToken, RefreshToken
from oauth2_provider.views import AuthorizationView

from apps.connector import auth, protocol

# Browsers may only reach the endpoint from the site itself or Claude's
# own pages; Claude's servers and Claude Code send no Origin at all
ALLOWED_ORIGINS = {"https://claude.ai", "https://claude.com"}


@csrf_exempt
def mcp(request):
    """The MCP endpoint: one JSON-RPC message per POST, answered in JSON.
    It offers no event stream, so GET (and DELETE, which ends a session
    it never starts) are refused."""
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response

    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS | {settings.SITE_URL}:
        return JsonResponse({"error": "Origin not allowed."}, status=403)

    access = auth.token_for(request)
    if access is None:
        return auth.challenge(request)

    try:
        message = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        error = protocol.RpcError(protocol.PARSE_ERROR, "Parse error")
        return JsonResponse(protocol._error(None, error), status=400)

    status, body = protocol.handle(access.user, message)
    if body is None:
        return HttpResponse(status=status)
    return JsonResponse(body, status=status)


def connections(user):
    """What the user has let in: one row per app, with when it was last
    given access, for the settings page."""
    apps = {}
    tokens = (
        AccessToken.objects.filter(user=user)
        .select_related("application")
        .order_by("-created")
    )
    for token in tokens:
        application = token.application
        if application is None or application.pk in apps:
            continue
        apps[application.pk] = {
            "id": application.pk,
            "name": application.name or "An app",
            "since": token.created,
        }
    for refresh in RefreshToken.objects.filter(user=user, revoked__isnull=True):
        application = refresh.application
        if application.pk not in apps:
            apps[application.pk] = {
                "id": application.pk,
                "name": application.name or "An app",
                "since": refresh.created,
            }
    return list(apps.values())


@login_required
@require_POST
def disconnect(request, application_id):
    """Take an app's access away: its tokens go, so it must be approved
    again to come back."""
    user = request.user
    AccessToken.objects.filter(user=user, application_id=application_id).delete()
    RefreshToken.objects.filter(user=user, application_id=application_id).delete()
    return redirect("/settings/connected/")


@login_required
def connected_index(request):
    """Settings → Connected apps: the connector's address, for adding it to
    Claude, and the apps the user has let in, each with a Disconnect."""
    context = {
        "page": "settings",
        "subapp": "connected",
        "connector_url": settings.CONNECTOR_URL,
        "connections": connections(request.user),
    }
    return render(request, "settings/connected.html", context)


def _is_android_app(application):
    return getattr(application, "client_id", None) == settings.ANDROID_CLIENT_ID


class ConsentView(AuthorizationView):
    """The toolkit's authorize page, naming where the app identifies itself
    from: the host of its client id when that is a web address (as
    Claude's is), else of where it sends the user back to. An app's name is
    its own to choose; its host is not. CloudPortal's own Android app
    (apps.api), registered by the site, has no host and says so."""

    def redirect(self, redirect_to, application):
        # The Android app is sent back by its own URI scheme, allowed for it
        # alone; every other app keeps the toolkit's allowed schemes
        if _is_android_app(application):
            scheme = urlparse(settings.ANDROID_REDIRECT_URI).scheme
            schemes = [*application.get_allowed_schemes(), scheme]
            return OAuth2ResponseRedirect(redirect_to, schemes)
        return super().redirect(redirect_to, application)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = context.get("application")
        context["android_app"] = _is_android_app(application)
        client_id = getattr(application, "client_id", "") or ""
        host = (
            urlparse(client_id).hostname if client_id.startswith("https://") else None
        )
        if not host:
            host = urlparse(context.get("redirect_uri") or "").hostname
        context["client_host"] = host or "an unknown site"
        return context
