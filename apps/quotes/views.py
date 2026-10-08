"""The Quotes settings tab: paste quotes in, mark the ones that always
show, take them out, and choose how the day's quote is picked."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.quotes import quotes
from apps.quotes.forms import QuoteForm
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
    if request.headers.get("HX-Request"):
        return render(request, "settings/quote_always.html", {"quote": quote})
    return redirect(SETTINGS_URL)


@login_required
def edit(request, id):
    """Change a quote's text, author or whether it shows every day."""
    quote = get_object_or_404(Quote, id=id, user=request.user)
    if request.method == "POST":
        form = QuoteForm(request.POST, instance=quote)
        if form.is_valid():
            form.save()
            return redirect(SETTINGS_URL)
    else:
        form = QuoteForm(instance=quote)
    context = {"page": "settings", "subapp": "quotes", "form": form, "quote": quote}
    return render(request, "settings/quote_form.html", context)


@login_required
@require_POST
def delete(request, id):
    quote = get_object_or_404(Quote, id=id, user=request.user)
    quote.delete()
    if request.headers.get("HX-Request"):
        quotes_left = Quote.objects.filter(user=request.user)
        return render(request, "settings/quotes_list.html", {"quotes": quotes_left})
    return redirect(SETTINGS_URL)


@login_required
def options(request, option, value):
    """Set how the day's quote is picked."""
    user = request.user
    if option == "mode" and value in quotes.MODES:
        user.quotes_mode = value
        user.save(update_fields=["quotes_mode"])
    return redirect(SETTINGS_URL)
