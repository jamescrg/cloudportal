"""The Security settings tab: two-step sign-in with an authenticator app
(accounts.totp).

Setting it up keeps the new secret in the session until a code from the
app confirms it, so a half-finished setup never locks anyone out. Turning
it off asks for the password and a code; the password tries count against
the sign-in cooldown, so a borrowed session can't be used to guess it."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from accounts import throttle, totp

SETUP_KEY = "totp_setup_secret"


def _render(request, **extra):
    user = request.user
    context = {
        "page": "settings",
        "subapp": "security",
        "enabled": bool(user.totp_secret),
        "codes_left": totp.recovery_codes_left(user) if user.totp_secret else 0,
    }
    secret = request.session.get(SETUP_KEY)
    if secret and not user.totp_secret:
        context["setup"] = {
            "qr": mark_safe(totp.qr_svg(totp.provisioning_uri(user, secret))),
            "key": totp.grouped(secret),
        }
    context.update(extra)
    return render(request, "settings/security.html", context)


@login_required
def index(request):
    """Show the Security settings tab."""
    return _render(request)


@login_required
@require_POST
def start(request):
    """Begin setting up: a new secret, shown as a QR code to scan."""
    if not request.user.totp_secret:
        request.session[SETUP_KEY] = totp.new_secret()
    return redirect("settings-security")


@login_required
@require_POST
def cancel(request):
    request.session.pop(SETUP_KEY, None)
    return redirect("settings-security")


@login_required
@require_POST
def confirm(request):
    """A code from the app proves it has the secret: turn it on, and show
    the recovery codes, once."""
    secret = request.session.get(SETUP_KEY)
    if not secret or request.user.totp_secret:
        return redirect("settings-security")
    step = totp.matching_step(secret, request.POST.get("code", ""))
    if step is None:
        return _render(
            request,
            setup_error="That code didn't match. Check the app and try the current one.",
        )
    totp.enable(request.user, secret, step)
    del request.session[SETUP_KEY]
    return _render(request, new_codes=totp.make_recovery_codes(request.user))


@login_required
@require_POST
def recovery_codes(request):
    """A fresh set of recovery codes, for a current code from the app."""
    user = request.user
    if not user.totp_secret:
        return redirect("settings-security")
    if not totp.verify(user, request.POST.get("code", "")):
        return _render(request, codes_error="That code didn't work.")
    return _render(request, new_codes=totp.make_recovery_codes(user))


@login_required
@require_POST
def disable(request):
    """Turn it off, given the password and a code (or a recovery code)."""
    user = request.user
    if not user.totp_secret:
        return redirect("settings-security")

    wait = throttle.cooldown_remaining(user.username)
    if wait:
        return _render(
            request,
            disable_error=f"Too many attempts. Try again in {throttle.describe(wait)}.",
        )
    if not user.check_password(request.POST.get("password", "")):
        throttle.record_failure(user.username)
        return _render(request, disable_error="That password isn't right.")
    if not totp.accept(user, request.POST.get("code", "")):
        throttle.record_failure(user.username)
        return _render(request, disable_error="That code didn't work.")

    totp.disable(user)
    return _render(request, turned_off=True)
