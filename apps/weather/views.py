from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.weather.service import has_location, place_name, report_for


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
