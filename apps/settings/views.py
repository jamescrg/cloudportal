import json

import google.oauth2.credentials
import google_auth_oauthlib.flow
import requests
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.finance.forms import CryptoSymbolForm, SecuritiesSymbolForm
from apps.finance.models import CryptoSymbol, SecuritiesSymbol
from apps.notes.models import Note
from apps.settings.forms import ChangePasswordForm, ProfileForm


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
    }
    return render(request, "settings/profile/index.html", context)


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


@login_required
def session_index(request):
    """Show the Session settings tab."""

    context = {
        "page": "settings",
        "subapp": "session",
    }
    return render(request, "settings/session.html", context)


@login_required
def notifications_index(request):
    context = {
        "page": "settings",
        "subapp": "notifications",
        "edit_email": request.GET.get("edit_email"),
    }
    return render(request, "settings/notifications.html", context)


@login_required
def notification_options(request, option, value):
    user = request.user
    val = True if value == "enable" else False
    if option == "email_reminders":
        user.email_reminders = val
    elif option == "sms_notifications":
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
                context = {
                    "page": "settings",
                    "subapp": "notifications",
                    "edit_email": True,
                    "email_error": "Please enter a valid email address.",
                }
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


@login_required
def encryption_index(request):
    """Show the Encryption settings tab."""
    notes = Note.objects.filter(user=request.user)
    context = {
        "page": "settings",
        "subapp": "encryption",
        "has_salt": bool(request.user.encryption_salt),
        "note_count": notes.count(),
        "encrypted_count": notes.filter(is_encrypted=True).count(),
    }
    return render(request, "settings/encryption.html", context)


@login_required
def encryption_save_salt(request):
    """Save the encryption salt generated client-side."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    body = json.loads(request.body)
    salt = body.get("salt", "").strip()

    if not salt:
        return JsonResponse({"error": "Salt is required"}, status=400)

    request.user.encryption_salt = salt
    request.user.save(update_fields=["encryption_salt"])

    return JsonResponse({"saved": True})


@login_required
def encryption_clear_salt(request):
    """Clear the encryption salt (disable encryption)."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    request.user.encryption_salt = ""
    request.user.save(update_fields=["encryption_salt"])

    return JsonResponse({"saved": True})


@login_required
def encryption_notes_list(request):
    """Return all notes as JSON for bulk encrypt/decrypt."""
    notes = Note.objects.filter(user=request.user).values(
        "id", "content", "is_encrypted"
    )
    return JsonResponse({"notes": list(notes)})


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
def tasks_options(request, option, value):
    """Set task-related options on the user."""
    user = request.user
    if option == "completion_mode" and value in ("complete", "archive", "delete"):
        user.task_completion_mode = value
        user.save(update_fields=["task_completion_mode"])
    return redirect("/settings/tasks/")


@login_required
def theme(request):
    """Sets the user's preferred  theme."""

    request.session["theme"] = request.POST["theme"]
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
