from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.weather.service import dismiss_alert, has_location, place_name, report_for


@login_required
def index(request):
    """The weather at the user's saved location: a report from One Call,
    or the page that asks the browser where they are."""
    user = request.user
    located = has_location(user)
    report = report_for(user) if located else None
    place = place_name(user) if report else ""
    context = {
        "page": "weather",
        "has_location": located,
        "report": report,
        "place": place,
    }
    return render(request, "weather/content.html", context)


@login_required
@require_POST
def dismiss(request):
    """Clear an alert from the user's page until it ends."""
    key = request.POST.get("key", "").strip()
    if not key:
        return JsonResponse({"success": False, "error": "No alert given"}, status=400)
    dismiss_alert(request.user, key)
    return JsonResponse({"success": True})
