"""The Quotes settings tab: paste quotes in, mark the ones that always
show, take them out, and choose how the day's quote is picked."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.quotes import quotes
from apps.quotes.models import Quote

SETTINGS_URL = "/settings/quotes/"


@login_required
def settings_index(request):
    context = {
        "page": "settings",
        "subapp": "quotes",
        "quotes": Quote.objects.filter(user=request.user),
    }
    return render(request, "settings/quotes.html", context)


@login_required
@require_POST
def add(request):
    """Keep the quotes pasted into the form, one per line."""
    quotes.add(request.user, request.POST.get("text", ""))
    return redirect(SETTINGS_URL)


@login_required
@require_POST
def toggle_always(request, id):
    quote = get_object_or_404(Quote, id=id, user=request.user)
    quote.always = not quote.always
    quote.save(update_fields=["always"])
    return redirect(SETTINGS_URL)


@login_required
@require_POST
def delete(request, id):
    quote = get_object_or_404(Quote, id=id, user=request.user)
    quote.delete()
    return redirect(SETTINGS_URL)


@login_required
def options(request, option, value):
    """Set how the day's quote is picked."""
    user = request.user
    if option == "mode" and value in quotes.MODES:
        user.quotes_mode = value
        user.save(update_fields=["quotes_mode"])
    return redirect(SETTINGS_URL)
