"""Who a request to the API comes from: the user behind its OAuth access
token, as for Claude's connector (apps.connector.auth), but for the API's
own address. A token restricted to a resource (RFC 8707) must be for the
API; one for the connector is refused here, as one for the API is there."""

import hashlib

from django.conf import settings
from django.http import JsonResponse
from oauth2_provider.models import AccessToken


def token_for(request):
    """The valid access token the request carries for the API, or None."""
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
    if not access.allows_audience(settings.API_URL):
        return None
    if access.user is None or not access.user.is_active:
        return None
    return access


def challenge(request):
    """The 401 that tells the app to refresh its token, or sign in again."""
    params = [f'scope="{settings.CONNECTOR_SCOPE}"']
    if request.headers.get("Authorization"):
        params.append('error="invalid_token"')
    response = JsonResponse(
        {"error": "Sign in to CloudPortal to continue."}, status=401
    )
    response["WWW-Authenticate"] = "Bearer " + ", ".join(params)
    return response
