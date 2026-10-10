import json
from urllib.parse import urlsplit

import google.oauth2.credentials
import google_auth_oauthlib.flow
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from accounts import totp
from accounts.models import NAV_ICONS
from apps.calendar import invitations, kosmos, sync as calendar_sync
from apps.common import notify
from apps.finance.forms import CryptoSymbolForm, SecuritiesSymbolForm
from apps.finance.models import CryptoSymbol, SecuritiesSymbol
from apps.notes.models import Note
from apps.settings.forms import ChangePasswordForm, ProfileForm
from config.context import (
    DEFAULT_THEME,
    RENAMED_THEMES,
    THEME_VARIANTS,
    THEMES,
    VARIANT_OF,
)


def _get_form_errors(form):
    errors = []
    for field, error_list in form.errors.items():
        if field == "__all__":
            errors.extend(error_list)
        else:
            errors.extend(f"{field.capitalize()}: {error}" for error in error_list)
    return ". ".join(errors)


@login_required
def profile_index(request):
    context = {
        "page": "settings",
        "subapp": "profile",
        "nav_icons": NAV_ICONS,
    }
    return render(request, "settings/profile/index.html", context)


@login_required
@require_POST
def nav_icon(request):
    """Choose the icon that stands for the user in the top bar. Only one
    of the set: any other name would point at an icon that isn't."""
    icon = request.POST.get("icon", "")
    if icon in dict(NAV_ICONS):
        request.user.nav_icon = icon
        request.user.save(update_fields=["nav_icon"])
    return redirect("settings-profile")


@login_required
def personal_profile(request, form_type=None):
    if request.method == "POST":
        if form_type == "profile":
            form = ProfileForm(request.POST, instance=request.user)

            if form.is_valid():
                profile = form.save(commit=False)
                profile.save()

                return HttpResponse("Profile updated successfully")
        elif form_type == "password":
            change_password_form = ChangePasswordForm(
                request.POST, instance=request.user
            )

            if change_password_form.is_valid():
                user = change_password_form.save(commit=True)
                user.save()

                return HttpResponse(
                    '<div class="success-msg">Password changed successfully</div>'
                )
            else:
                errors = _get_form_errors(change_password_form)

                return HttpResponse(f'<div class="error-msg">{errors}</div>')

    else:
        form = ProfileForm(instance=request.user)
        change_password_form = ChangePasswordForm(instance=request.user)

    context = {
        "user": request.user,
        "form": form,
        "change_password_form": change_password_form,
    }

    return render(request, "settings/profile/profile.html", context)


@login_required
def index(request):
    """Show the settings page — Theme tab."""

    context = {
        "page": "settings",
        "subapp": "theme",
    }
    return render(request, "settings/content.html", context)


@login_required
def homepage_index(request):
    """Show the Homepage settings tab."""

    context = {
        "page": "settings",
        "subapp": "homepage",
    }
    return render(request, "settings/homepage.html", context)


@login_required
def google_index(request):
    """Show the Google settings tab."""

    logged_in = bool(request.user.google_credentials)

    context = {
        "page": "settings",
        "subapp": "google",
        "logged_in": logged_in,
    }
    return render(request, "settings/google.html", context)


def _ntfy_subscribe_link(user):
    """The link that opens the ntfy app on a phone, subscribing it to the
    user's topic (ntfy://server/topic)."""
    from urllib.parse import urlsplit

    server = urlsplit(user.ntfy_server)
    link = f"ntfy://{server.netloc}{server.path.rstrip('/')}/{notify.topic(user)}"
    if server.scheme == "http":
        link += "?secure=false"
    return link


def _notifications_context(request, **extra):
    return {
        "page": "settings",
        "subapp": "notifications",
        "ntfy_subscribe_link": _ntfy_subscribe_link(request.user),
        # the link as a QR code too, for the phone's camera to read
        "ntfy_qr": mark_safe(totp.qr_svg(_ntfy_subscribe_link(request.user))),
        "ntfy_topic_here": notify.topic(request.user),
        "ntfy_suffix": settings.NTFY_TOPIC_SUFFIX,
        "not_production": settings.NOT_PRODUCTION,
        "email_notifications": settings.EMAIL_NOTIFICATIONS,
        "test_result": request.GET.get("test"),
        "test_error": request.session.pop("ntfy_test_error", ""),
    } | extra


def _new_ntfy_topic():
    """A topic no one will guess: ntfy delivers a topic's messages to
    anyone who names it."""
    import secrets

    return "cpl-" + secrets.token_urlsafe(24)


@login_required
def notifications_index(request):
    return render(
        request, "settings/notifications.html", _notifications_context(request)
    )


@login_required
@require_POST
def notify_by(request):
    """Choose the default channel for notifications: email, ntfy (push) or
    the home page. Choosing ntfy the first time gives the user their
    topic."""
    user = request.user
    choice = request.POST.get("notify_by")
    if choice in dict(user.NOTIFY_CHOICES):
        user.notify_by = choice
        if choice == "ntfy" and not user.ntfy_topic:
            user.ntfy_topic = _new_ntfy_topic()
        user.save(update_fields=["notify_by", "ntfy_topic"])
    return redirect("settings-notifications")


def _save_ntfy(request):
    """Save the ntfy server and access token from the form. Returns an
    error message, or "" when saved."""
    from django.core.exceptions import ValidationError
    from django.core.validators import URLValidator

    user = request.user
    server = request.POST.get("ntfy_server", "").strip() or "https://ntfy.sh"
    try:
        URLValidator(schemes=["http", "https"])(server)
    except ValidationError:
        return "Enter the server's address, like https://ntfy.sh."
    user.ntfy_server = server.rstrip("/")
    user.ntfy_token = request.POST.get("ntfy_token", "").strip()
    user.save(update_fields=["ntfy_server", "ntfy_token"])
    return ""


@login_required
@require_POST
def ntfy_settings(request):
    error = _save_ntfy(request)
    if error:
        return render(
            request,
            "settings/notifications.html",
            _notifications_context(request, ntfy_error=error),
        )
    return redirect("settings-notifications")


@login_required
@require_POST
def ntfy_new_topic(request):
    """A new topic, for one that has got out: the old one stops."""
    request.user.ntfy_topic = _new_ntfy_topic()
    request.user.save(update_fields=["ntfy_topic"])
    return redirect("settings-notifications")


@login_required
@require_POST
def ntfy_test(request):
    """Save the form as it stands, then push a test to the topic."""
    error = _save_ntfy(request)
    if error:
        return render(
            request,
            "settings/notifications.html",
            _notifications_context(request, ntfy_error=error),
        )
    result = notify.test_message(request.user)
    if not result["success"]:
        request.session["ntfy_test_error"] = result.get("error", "")
    return redirect(
        reverse("settings-notifications")
        + ("?test=sent" if result["success"] else "?test=failed")
    )


@login_required
def notification_options(request, option, value):
    user = request.user
    val = True if value == "enable" else False
    if option == "sms_notifications":
        user.sms_notifications = val
    user.save()
    return redirect("/settings/notifications/")


@login_required
def notification_email(request):
    if request.method == "POST":
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        email = request.POST.get("notification_email", "").strip()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                context = _notifications_context(
                    request, email_error="Please enter a valid email address."
                )
                return render(request, "settings/notifications.html", context)
        request.user.notification_email = email
        request.user.save(update_fields=["notification_email"])
    return redirect("/settings/notifications/")


@login_required
def google_login(request):
    """Direct the user to their login page to obtain an authorization code.

    Notes:
        Based on sample code from:
        https://developers.google.com/identity/protocols/oauth2/web-server
    """

    # sets the url to return to when an authorization code has been obtained
    redirect_uri = "https://" + request.get_host() + "/settings/google/store"

    # builds the url to go to in order to obtain the authorization code
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        "/home/james/.google/cp.json",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/contacts",
        ],
    )
    flow.redirect_uri = redirect_uri

    authorization_url, state = flow.authorization_url(
        # Enable offline access so that you can refresh an access token without
        # re-prompting the user for permission. Recommended for web server apps.
        access_type="offline",
        prompt="consent",
        # Enable incremental authorization. Recommended as a best practice.
        include_granted_scopes="true",
    )

    # this is to prevent cross site scripting attacks
    request.session["state"] = state

    return redirect(authorization_url)


@login_required
def google_store(request):
    """Store the user's authorization code in the database.

    Notes:
        The user's authorization code is a json string,
        which is stored in the user's "google_credentials" attribute.
    """

    redirect_uri = "https://" + request.get_host() + "/settings/google/store"

    state = request.session["state"]
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        "/home/james/.google/cp.json",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/contacts",
        ],
        state=state,
    )
    flow.redirect_uri = redirect_uri

    authorization_response = request.build_absolute_uri()
    flow.fetch_token(authorization_response=authorization_response)

    # get the user credentials and package them as a json string
    credentials = flow.credentials
    google_credentials_json = credentials.to_json()

    # save the json credentials to the database
    user = request.user
    user.google_credentials = google_credentials_json
    user.save()

    # Events kept here before the connection, and any pushes that failed
    # while it was down, go to Google Calendar now.
    calendar_sync.reconcile(user)

    return redirect("/settings/google/")


@login_required
def google_logout(request):
    """Disconnects the user's google account from the app.

    Notes:
        Contacts google and revokes the user's auth code.
        Then deletes the user's code from the database.
    """

    # get / build the user credentials
    user = request.user
    credentials = user.google_credentials
    credentials = json.loads(credentials)
    credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
        credentials
    )

    # use the credentials to revoke access
    requests.post(
        "https://oauth2.googleapis.com/revoke",
        params={"token": credentials.token},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    # delete the credentials from the database
    user.google_credentials = None
    user.save()

    return redirect("/settings/google/")


# The PBKDF2 round counts a client may record: the old fixed count at the
# low end, and a ceiling well above anything a phone derives in a second
ITERATIONS_MIN = 100_000
ITERATIONS_MAX = 10_000_000
ENCRYPTION_FIELDS = [
    "encryption_salt",
    "encryption_wrapped_key",
    "encryption_recovery_salt",
    "encryption_recovery_wrapped_key",
    "encryption_by_default",
]


@login_required
def encryption_index(request):
    """Show the Encryption settings tab."""
    user = request.user
    notes = Note.objects.filter(user=user)
    # what the page's script needs (static/js/encryption-settings.js);
    # the sealed keys are no secret, only the passphrase opens them
    config = {
        "salt": user.encryption_salt,
        "iterations": user.encryption_iterations,
        "wrappedKey": user.encryption_wrapped_key,
        "recoverySalt": user.encryption_recovery_salt,
        "recoveryWrappedKey": user.encryption_recovery_wrapped_key,
        "byDefault": user.encryption_by_default,
        "urls": {
            "notes": reverse("settings-encryption-notes"),
            "update": reverse("settings-encryption-notes-update"),
            "saveSalt": reverse("settings-encryption-save-salt"),
            "clearSalt": reverse("settings-encryption-clear-salt"),
            "recovery": reverse("settings-encryption-recovery"),
            "byDefaultOn": reverse("settings-encryption-by-default", args=["on"]),
        },
    }
    context = {
        "page": "settings",
        "subapp": "encryption",
        "has_salt": bool(user.encryption_salt),
        "sealed": bool(user.encryption_wrapped_key),
        "has_recovery": bool(user.encryption_recovery_wrapped_key),
        "by_default_on": reverse("settings-encryption-by-default", args=["on"]),
        "by_default_off": reverse("settings-encryption-by-default", args=["off"]),
        "note_count": notes.count(),
        "encrypted_count": notes.filter(is_encrypted=True).count(),
        "plain_count": notes.filter(is_encrypted=False).count(),
        "config": config,
    }
    return render(request, "settings/encryption.html", context)


def _encryption_body(request):
    try:
        return json.loads(request.body)
    except ValueError:
        return {}


@login_required
@require_POST
def encryption_save_salt(request):
    """Record what the browser made when a passphrase was set or changed:
    the salt, the round count, and the note key sealed under the
    passphrase (static/js/crypto.js). The passphrase and the key never
    arrive here."""
    body = _encryption_body(request)
    salt = str(body.get("salt", "")).strip()
    wrapped_key = str(body.get("wrapped_key", "")).strip()

    if not salt:
        return JsonResponse({"error": "Salt is required"}, status=400)
    if not wrapped_key:
        return JsonResponse({"error": "Wrapped key is required"}, status=400)
    # the PBKDF2 round count the sealing key was derived with, kept beside
    # the salt so the key can be derived again; bounded so a typo can't
    # lock a browser up for minutes or weaken the key below the old default
    try:
        iterations = int(body.get("iterations"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Iterations are required"}, status=400)
    if not ITERATIONS_MIN <= iterations <= ITERATIONS_MAX:
        return JsonResponse({"error": "Iterations out of range"}, status=400)

    user = request.user
    user.encryption_salt = salt
    user.encryption_iterations = iterations
    user.encryption_wrapped_key = wrapped_key
    user.save(
        update_fields=[
            "encryption_salt",
            "encryption_iterations",
            "encryption_wrapped_key",
        ]
    )
    return JsonResponse({"saved": True})


@login_required
@require_POST
def encryption_clear_salt(request):
    """Forget everything about encryption: the browser has decrypted every
    note first (the Disable flow)."""
    user = request.user
    user.encryption_salt = ""
    user.encryption_wrapped_key = ""
    user.encryption_recovery_salt = ""
    user.encryption_recovery_wrapped_key = ""
    user.encryption_by_default = True
    user.save(update_fields=ENCRYPTION_FIELDS)
    return JsonResponse({"saved": True})


@login_required
@require_POST
def encryption_save_recovery(request):
    """Record the note key sealed under a recovery code, with the code's
    own salt; an empty body clears the recovery code."""
    body = _encryption_body(request)
    salt = str(body.get("recovery_salt", "")).strip()
    wrapped_key = str(body.get("recovery_wrapped_key", "")).strip()
    if bool(salt) != bool(wrapped_key):
        return JsonResponse({"error": "Salt and wrapped key go together"}, status=400)
    user = request.user
    user.encryption_recovery_salt = salt
    user.encryption_recovery_wrapped_key = wrapped_key
    user.save(
        update_fields=["encryption_recovery_salt", "encryption_recovery_wrapped_key"]
    )
    return JsonResponse({"saved": True, "has_recovery": bool(salt)})


@login_required
@require_POST
def encryption_by_default(request, state):
    """Whether a new note starts encrypted: the switch on the settings
    page posts a form here and comes back to the page; the encrypt-all
    flow posts JSON and gets JSON."""
    user = request.user
    user.encryption_by_default = state == "on"
    user.save(update_fields=["encryption_by_default"])
    if request.content_type == "application/json":
        return JsonResponse({"saved": True, "enabled": user.encryption_by_default})
    return redirect("settings-encryption")


@login_required
def encryption_notes_list(request):
    """Every note of the user's as JSON, ciphertext and all, for the
    browser's bulk work: encrypt-all, a passphrase change from the old
    scheme, disable, and search inside encrypted notes (notes-search.js),
    which is why each carries its title, its page and its folder."""
    notes = [
        {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "is_encrypted": note.is_encrypted,
            "url": reverse("notes:note-view", args=[note.id]),
            "folder_name": note.folder.name if note.folder_id else "",
            "folder_url": (
                reverse("folder-select", args=[note.folder_id, "notes"])
                if note.folder_id
                else ""
            ),
        }
        for note in Note.objects.filter(user=request.user).select_related("folder")
    ]
    return JsonResponse({"notes": notes})


@login_required
@require_POST
def encryption_notes_bulk_update(request):
    """Bulk update notes content and is_encrypted flag."""
    body = json.loads(request.body)
    notes_data = body.get("notes", [])

    for item in notes_data:
        note_id = item.get("id")
        if not note_id:
            continue
        try:
            note = Note.objects.get(pk=note_id, user=request.user)
        except Note.DoesNotExist:
            continue
        note.content = item.get("content", "")
        note.is_encrypted = item.get("is_encrypted", False)
        note.save(update_fields=["content", "is_encrypted", "updated_at"])

    return JsonResponse({"saved": True})


@login_required
def tasks_settings_index(request):
    """Show the Tasks settings tab."""
    context = {
        "page": "settings",
        "subapp": "tasks",
    }
    return render(request, "settings/tasks.html", context)


@login_required
@require_POST
def time_zone(request):
    """Record where the user is now, as their browser reports it on each
    page load. A name that is not a zone changes nothing."""
    from apps.calendar.models import is_zone

    name = request.POST.get("time_zone", "").strip()
    if not is_zone(name):
        return HttpResponse("Unknown time zone", status=400)
    if request.user.time_zone != name:
        request.user.time_zone = name
        request.user.save(update_fields=["time_zone"])
    return HttpResponse(status=204)


def _calendar_context(request, **extra):
    return {
        "page": "settings",
        "subapp": "calendar",
        "inbound_domain": settings.CALENDAR_INBOUND_DOMAIN,
        "inbound_address": invitations.inbound_address(request.user),
        "kosmos_test": request.session.pop("kosmos_test", ""),
        "kosmos_test_error": request.session.pop("kosmos_test_error", ""),
        **extra,
    }


@login_required
def calendar_settings_index(request):
    """Show the Calendar settings tab."""
    return render(request, "settings/calendar.html", _calendar_context(request))


@login_required
def calendar_options(request, option, value):
    """Set calendar-related options on the user."""
    user = request.user
    if option == "google_sync" and value in ("on", "off"):
        user.calendar_sync = value == "on"
        user.save(update_fields=["calendar_sync"])
        # Turning sync on adopts the events kept here so far, as connecting
        # a Google account does.
        if user.calendar_sync:
            calendar_sync.reconcile(user)
    # A new forwarding address retires the old one at once
    if option == "inbound_address" and value == "new":
        user.calendar_inbound_token = invitations.new_token()
        user.save(update_fields=["calendar_inbound_token"])
    if option == "inbound_address" and value == "clear":
        user.calendar_inbound_token = None
        user.save(update_fields=["calendar_inbound_token"])
    return redirect("/settings/calendar/")


@login_required
@require_POST
def calendar_kosmos(request):
    """Save where the user's Kosmos is and their token for it, or try the
    connection, or forget it."""
    user = request.user
    action = request.POST.get("action", "save")
    if action == "clear":
        user.kosmos_url = ""
        user.kosmos_token = ""
        user.save(update_fields=["kosmos_url", "kosmos_token"])
        return redirect("settings-calendar")
    url = request.POST.get("kosmos_url", "").strip().rstrip("/")
    token = request.POST.get("kosmos_token", "").strip()
    split = urlsplit(url)
    if not url or split.scheme not in ("http", "https") or not split.netloc:
        return render(
            request,
            "settings/calendar.html",
            _calendar_context(
                request,
                kosmos_error="Enter the address of your Kosmos, like https://kosmos.example.com.",
            ),
        )
    user.kosmos_url = url
    user.kosmos_token = token
    user.save(update_fields=["kosmos_url", "kosmos_token"])
    if action == "test":
        result = kosmos.check(user)
        if result["ok"]:
            request.session["kosmos_test"] = (
                f"Connected: Kosmos has {result['count']} event(s) for you this month."
            )
        else:
            request.session["kosmos_test_error"] = result["error"]
    return redirect("settings-calendar")


@login_required
@require_POST
def calendar_forward_from(request):
    """Save the addresses, besides the user's own, that invitations may be
    forwarded from."""
    user = request.user
    user.calendar_forward_from = request.POST.get("calendar_forward_from", "").strip()
    user.save(update_fields=["calendar_forward_from"])
    return redirect("/settings/calendar/")


@login_required
def tasks_options(request, option, value):
    """Set task-related options on the user."""
    user = request.user
    if option == "completion_mode" and value in ("complete", "archive", "delete"):
        user.task_completion_mode = value
        user.save(update_fields=["task_completion_mode"])
    return redirect("/settings/tasks/")


def _current_theme(request):
    name = request.session.get("theme", "")
    return RENAMED_THEMES.get(name, name) or DEFAULT_THEME


@login_required
def theme(request):
    """Sets the theme for this device, in its session. Only a theme there
    is: any other name would point the page at a stylesheet that isn't.
    The page offers the base themes; choosing one keeps the atmosphere
    as it is, so a device on Hojicha Steam that picks Matcha gets Matcha
    Lavender."""

    name = request.POST.get("theme", "")
    name = RENAMED_THEMES.get(name, name)
    if name in THEMES:
        atmosphere = _current_theme(request) in THEME_VARIANTS
        if atmosphere and name in VARIANT_OF:
            name = VARIANT_OF[name]
        request.session["theme"] = name
    return redirect("/settings/")


@login_required
@require_POST
def theme_atmosphere(request):
    """Turns the atmosphere on or off for this device: the theme's
    atmospheric variant, or its base."""
    current = _current_theme(request)
    base = THEME_VARIANTS.get(current, current)
    on = request.POST.get("atmosphere") == "on"
    request.session["theme"] = VARIANT_OF[base] if on and base in VARIANT_OF else base
    return redirect("/settings/")


@login_required
def search_engine(request):
    """Sets the user's preferred search engine."""
    user = request.user
    user.search_engine = request.POST["search_engine"]
    user.save()

    # Handle HTMX requests
    if request.headers.get("HX-Request"):
        # Import here to avoid circular imports
        from apps.home.views import get_search_context

        # Get updated search context
        context = get_search_context(user)

        # Return just the search section
        return render(request, "home/search.html", context)

    return redirect("/home")


@login_required
def home_options(request, option, value):
    """Sets the user's home page options"""
    user = request.user

    if value == "enable":
        value = 1
    else:
        value = 0

    if option == "events":
        user.home_events = value
    if option == "tasks":
        user.home_tasks = value
    if option == "due_tasks":
        user.home_due_tasks = value
    if option == "weather":
        user.home_weather = value
    if option == "quotes":
        user.home_quotes = value
    if option == "icons":
        user.home_icons = value
    if option == "icons_muted":
        user.home_icons_muted = value

    user.save()
    return redirect("/settings/homepage/")


@login_required
def crypto_symbols(request):
    """Display and manage crypto symbols for the user."""
    symbols = CryptoSymbol.objects.filter(user=request.user).order_by("symbol")
    context = {
        "page": "settings",
        "subapp": "crypto",
        "symbols": symbols,
    }
    return render(request, "settings/crypto_symbols.html", context)


@login_required
def crypto_symbol_add(request):
    """Add a new crypto symbol."""
    if request.method == "POST":
        form = CryptoSymbolForm(request.POST)
        if form.is_valid():
            symbol = form.save(commit=False)
            symbol.user = request.user
            symbol.save()
            return redirect("settings-crypto-symbols")
    else:
        form = CryptoSymbolForm()

    context = {
        "page": "settings",
        "subapp": "crypto",
        "form": form,
        "action": "Add",
    }
    return render(request, "settings/crypto_symbol_form.html", context)


@login_required
def crypto_symbol_edit(request, id):
    """Edit an existing crypto symbol."""
    symbol = get_object_or_404(CryptoSymbol, id=id, user=request.user)

    if request.method == "POST":
        form = CryptoSymbolForm(request.POST, instance=symbol)
        if form.is_valid():
            form.save()
            return redirect("settings-crypto-symbols")
    else:
        form = CryptoSymbolForm(instance=symbol)

    context = {
        "page": "settings",
        "subapp": "crypto",
        "form": form,
        "symbol": symbol,
        "action": "Edit",
    }
    return render(request, "settings/crypto_symbol_form.html", context)


@login_required
def crypto_symbol_delete(request, id):
    """Delete a crypto symbol."""
    symbol = get_object_or_404(CryptoSymbol, id=id, user=request.user)
    symbol.delete()
    return redirect("settings-crypto-symbols")


@login_required
def securities_symbols(request):
    """Display and manage securities symbols for the user."""
    symbols = SecuritiesSymbol.objects.filter(user=request.user).order_by("symbol")
    context = {
        "page": "settings",
        "subapp": "securities",
        "symbols": symbols,
    }
    return render(request, "settings/securities_symbols.html", context)


@login_required
def securities_symbol_add(request):
    """Add a new securities symbol."""
    if request.method == "POST":
        form = SecuritiesSymbolForm(request.POST)
        if form.is_valid():
            symbol = form.save(commit=False)
            symbol.user = request.user
            symbol.save()
            return redirect("settings-securities-symbols")
    else:
        form = SecuritiesSymbolForm()

    context = {
        "page": "settings",
        "subapp": "securities",
        "form": form,
        "action": "Add",
    }
    return render(request, "settings/securities_symbol_form.html", context)


@login_required
def securities_symbol_edit(request, id):
    """Edit an existing securities symbol."""
    symbol = get_object_or_404(SecuritiesSymbol, id=id, user=request.user)

    if request.method == "POST":
        form = SecuritiesSymbolForm(request.POST, instance=symbol)
        if form.is_valid():
            form.save()
            return redirect("settings-securities-symbols")
    else:
        form = SecuritiesSymbolForm(instance=symbol)

    context = {
        "page": "settings",
        "subapp": "securities",
        "form": form,
        "symbol": symbol,
        "action": "Edit",
    }
    return render(request, "settings/securities_symbol_form.html", context)


@login_required
def securities_symbol_delete(request, id):
    """Delete a securities symbol."""
    symbol = get_object_or_404(SecuritiesSymbol, id=id, user=request.user)
    symbol.delete()
    return redirect("settings-securities-symbols")
