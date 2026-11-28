"""Who a request to the connector comes from: the user behind its OAuth
access token (issued by django-oauth-toolkit when the user approved
Claude), or no one, answered with the challenge that starts Claude's
sign-in."""

import hashlib

from django.conf import settings
from django.http import JsonResponse
from oauth2_provider.models import AccessToken


def metadata_url():
    """Where the connector's protected-resource metadata is (RFC 9728): the
    well-known path with the connector's own path after it."""
    return f"{settings.SITE_URL}/.well-known/oauth-protected-resource/mcp"


def token_for(request):
    """The valid access token the request carries for the connector, or
    None. A token restricted to a resource (RFC 8707, as Claude's are) must
    be for this one."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    checksum = hashlib.sha256(token.encode("utf-8")).hexdigest()
    access = (
        AccessToken.objects.select_related("user", "application")
        .filter(token_checksum=checksum)
        .first()
    )
    if access is None or not access.is_valid([settings.CONNECTOR_SCOPE]):
        return None
    if not access.allows_audience(settings.CONNECTOR_URL):
        return None
    # The Android apps' tokens are for the mobile API (apps.api) alone,
    # even one asked for without naming the API as its resource
    application = access.application
    if application is not None and application.client_id in settings.ANDROID_APPS:
        return None
    if access.user is None or not access.user.is_active:
        return None
    return access


def challenge(request):
    """The 401 that tells Claude to sign in, and where to find out how."""
    params = [
        f'resource_metadata="{metadata_url()}"',
        f'scope="{settings.CONNECTOR_SCOPE}"',
    ]
    if request.headers.get("Authorization"):
        params.append('error="invalid_token"')
    response = JsonResponse(
        {"error": "Sign in to CloudPortal to continue."}, status=401
    )
    response["WWW-Authenticate"] = "Bearer " + ", ".join(params)
    return response
