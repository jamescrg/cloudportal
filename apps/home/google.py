import json
from datetime import date, datetime, timedelta

import google.oauth2.credentials
from apiclient.discovery import build
from dateutil.parser import parse
from django.shortcuts import get_object_or_404

from accounts.models import CustomUser


def build_service(user_id):
    user = get_object_or_404(CustomUser, pk=user_id)
    credentials = user.google_credentials

    if credentials:
        credentials = json.loads(credentials)
        credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
            credentials
        )
        service = build("calendar", "v3", credentials=credentials)
        return service
    else:
        return False


def get_events(user_id):
    service = build_service(user_id)

    now = datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
    one_week = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            timeMax=one_week,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])

    if events:
        events_simplified = []

        for event in events:
            event_simple = {}
            start = event["start"].get("dateTime", event["start"].get("date"))
            start = parse(start)

            event_simple["date"] = start.strftime("%Y-%m-%d")
            event_simple["weekday"] = start.strftime("%A")
            event_simple["month"] = start.strftime("%B")

            event_simple["time"] = start.strftime("%I:%M %p")
            if event_simple["time"] == "12:00 AM":
                event_simple["time"] = ""

            event_simple["summary"] = event["summary"]

            today = date.today()
            pydate = date.fromisoformat(event_simple["date"])

            if pydate == today:
                event_simple["soon"] = "soon"
            else:
                event_simple["soon"] = ""

            events_simplified.append(event_simple)

        events_simplified = [
            i
            for i in events_simplified
            if not (i["summary"] == "Change water fountain filter")
        ]

        return events_simplified

    else:
        return None
