"""Two-step sign-in with an authenticator app.

The codes are TOTP (RFC 6238), the standard Google Authenticator and every
other authenticator app speak: six digits from a secret the app and the
site share, changing every 30 seconds. A code is taken from one step either
side of now, for clocks that have drifted, and never twice: the step of the
last code taken is kept, and only a later one is accepted.

Recovery codes stand in for the app when the phone is lost. Each works
once, and only its hash is kept."""

import hashlib
import hmac
import secrets
import time

import pyotp
import segno
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import CustomUser, RecoveryCode

RECOVERY_CODE_COUNT = 10


def new_secret():
    return pyotp.random_base32()


def issuer():
    """The name the app files the entry under. Off production it says so,
    or an account set up on both would show two entries alike."""
    return settings.SITE_NAME + (" (dev)" if settings.NOT_PRODUCTION else "")


def provisioning_uri(user, secret):
    """The otpauth:// link the QR code carries: the app files the entry
    under the site's name and the username."""
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=issuer())


def qr_svg(uri):
    """The QR code as inline SVG, dark on light whatever the theme, so any
    phone camera can read it."""
    return segno.make(uri, error="m").svg_inline(
        scale=5, border=2, dark="#000", light="#fff"
    )


def grouped(secret):
    """The secret in fours, for typing into an app by hand."""
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))  # noqa: E203


def _digits(code):
    return "".join(c for c in (code or "") if c.isdigit())


def matching_step(secret, code):
    """The 30-second step whose code ``code`` is, within one step of now;
    None if it is none of them."""
    code = _digits(code)
    if not secret or len(code) != 6:
        return None
    otp = pyotp.TOTP(secret)
    now = int(time.time()) // otp.interval
    for step in (now, now - 1, now + 1):
        if hmac.compare_digest(otp.generate_otp(step), code):
            return step
    return None


def verify(user, code):
    """Whether ``code`` is a current code from the user's app that hasn't
    been used. Taking it moves the user's last step on, in one guarded
    update, so two requests racing with the same code can't both win."""
    step = matching_step(user.totp_secret, code)
    if step is None:
        return False
    taken = (
        CustomUser.objects.filter(pk=user.pk)
        .filter(Q(totp_last_step__isnull=True) | Q(totp_last_step__lt=step))
        .update(totp_last_step=step)
    )
    if taken:
        user.totp_last_step = step
    return bool(taken)


def enable(user, secret, step):
    """Turn the app on for the user, the code that confirmed it already
    spent."""
    user.totp_secret = secret
    user.totp_last_step = step
    user.save(update_fields=["totp_secret", "totp_last_step"])


def disable(user):
    user.totp_secret = ""
    user.totp_last_step = None
    user.save(update_fields=["totp_secret", "totp_last_step"])
    RecoveryCode.objects.filter(user=user).delete()


def _normalise(code):
    return "".join(c for c in (code or "").lower() if c.isalnum())


def _hash(code):
    return hashlib.sha256(_normalise(code).encode()).hexdigest()


def make_recovery_codes(user):
    """A fresh set of recovery codes, replacing any before; returned once,
    to be shown, and kept only as hashes."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:]}")
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create(
        RecoveryCode(user=user, code_hash=_hash(code)) for code in codes
    )
    return codes


def use_recovery_code(user, code):
    """Whether ``code`` is one of the user's unused recovery codes; using it
    spends it."""
    if len(_normalise(code)) != 10:
        return False
    return bool(
        RecoveryCode.objects.filter(
            user=user, code_hash=_hash(code), used_at__isnull=True
        ).update(used_at=timezone.now())
    )


def recovery_codes_left(user):
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


def accept(user, code):
    """A code from the app, or failing that a recovery code."""
    return verify(user, code) or use_recovery_code(user, code)
