"""The mobile sync API, for the CloudPortal Android app: GET sync and POST
ops, each with an OAuth access token (apps.api.auth); no cookies, no CSRF.
Both sides keep to one contract (v1): what is sent is in apps.api.sync,
what is applied in apps.api.ops."""

import json

from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from apps.api import auth, ops as op_types
from apps.api.sync import snapshot

# 200 ops of a few hundred bytes each fit many times over
MAX_BODY = 1024 * 1024


def _answer(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _bad_request(message):
    return _answer({"error": message}, status=400)


def _not_allowed(method):
    response = HttpResponse(status=405)
    response["Allow"] = method
    return response


@csrf_exempt
def sync(request):
    if request.method != "GET":
        return _not_allowed("GET")
    access = auth.token_for(request)
    if access is None:
        return auth.challenge(request)
    return _answer(snapshot(access.user, request.GET.get("cursor") or None))


@csrf_exempt
def ops(request):
    if request.method != "POST":
        return _not_allowed("POST")
    access = auth.token_for(request)
    if access is None:
        return auth.challenge(request)

    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        return _bad_request("The request is too large.")
    try:
        body = request.body
        if len(body) > MAX_BODY:
            return _bad_request("The request is too large.")
        message = json.loads(body)
    except RequestDataTooBig:
        return _bad_request("The request is too large.")
    except (ValueError, UnicodeDecodeError):
        return _bad_request("The body must be JSON.")

    queued = message.get("ops") if isinstance(message, dict) else None
    if not isinstance(queued, list) or not all(isinstance(o, dict) for o in queued):
        return _bad_request('The body must be {"ops": [ {...}, ... ]}.')
    if len(queued) > op_types.MAX_OPS:
        return _bad_request(f"At most {op_types.MAX_OPS} ops at a time.")

    user = access.user
    return _answer({"results": [op_types.apply(user, op) for op in queued]})
