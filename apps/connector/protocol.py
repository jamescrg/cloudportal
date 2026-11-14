"""The Model Context Protocol, as much of it as the connector needs: a
stateless server answering each POST with plain JSON (no event streams,
no sessions).

Claude's clients are partway between two eras of the protocol, so both
are served. The older one opens with ``initialize`` and negotiates a
version; the newer (2026-07-28) has no handshake, each request carrying
its version in ``params._meta``, and asks ``server/discover`` for what the
server offers. Some clients send a version header that disagrees with the
body, so the body is trusted and the header not held against them.
"""

import json
import logging

from apps.connector import tools

logger = logging.getLogger(__name__)

CURRENT = "2026-07-28"
LEGACY = ["2025-11-25", "2025-06-18", "2025-03-26"]
SUPPORTED = [CURRENT, *LEGACY]
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"

SERVER_INFO = {"name": "minhome", "title": "Minhome", "version": "1.0.0"}
CAPABILITIES = {"tools": {"listChanged": False}}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_VERSION = -32022


class RpcError(Exception):
    def __init__(self, code, message, data=None, status=200):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.status = status


def instructions(user):
    zone = user.time_zone
    return (
        "Minhome is the user's own organizer: their task list and calendar. "
        f"Dates are YYYY-MM-DD and times 24-hour HH:MM, in the user's time "
        f"zone ({zone}); work out relative days (today, next Friday) in that "
        f"zone, where today is {tools._today(user).isoformat()}. Look tasks "
        "and events up by their id from find_tasks or list_events before "
        "changing them. Nothing can be deleted through these tools; the user "
        "deletes on the site."
    )


def _result(message_id, result):
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id, error):
    body = {"code": error.code, "message": error.message}
    if error.data is not None:
        body["data"] = error.data
    return {"jsonrpc": "2.0", "id": message_id, "error": body}


def _call_tool(user, params):
    name = params.get("name")
    tool = tools.BY_NAME.get(name)
    if tool is None:
        raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    try:
        output = tool["run"](user, args)
    except tools.ToolError as problem:
        return {"content": [{"type": "text", "text": str(problem)}], "isError": True}
    logger.info("connector: %s ran %s", user.username, name)
    return {
        "content": [{"type": "text", "text": json.dumps(output, indent=1)}],
        "structuredContent": output,
        "isError": False,
    }


def handle(user, message):
    """Answer one JSON-RPC message from Claude: (HTTP status, body), the
    body None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        error = RpcError(INVALID_REQUEST, "Expected one JSON-RPC 2.0 message.")
        return 400, _error(None, error)

    method = message.get("method")
    message_id = message.get("id")
    if "id" not in message:
        # A notification (initialized, cancelled): nothing to answer
        return 202, None

    params = message.get("params") or {}
    if not isinstance(params, dict):
        return 400, _error(message_id, RpcError(INVALID_PARAMS, "Bad params."))
    meta = params.get("_meta") or {}
    asked = meta.get(VERSION_KEY) if isinstance(meta, dict) else None

    try:
        if asked and asked not in SUPPORTED:
            raise RpcError(
                UNSUPPORTED_VERSION,
                "Unsupported protocol version",
                {"supported": SUPPORTED, "requested": asked},
                status=400,
            )
        result = _dispatch(user, method, params)
    except RpcError as error:
        if error.code == METHOD_NOT_FOUND and asked:
            error.status = 404
        return error.status, _error(message_id, error)
    except Exception:
        logger.exception("connector: %s failed", method)
        error = RpcError(INTERNAL_ERROR, "Something went wrong in Minhome.")
        return 500, _error(message_id, error)

    # The newer era marks every result complete
    if asked:
        result = {"resultType": "complete", **result}
    return 200, _result(message_id, result)


def _dispatch(user, method, params):
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in LEGACY else LEGACY[0]
        logger.info(
            "connector: initialize from %s asking %s, given %s",
            (params.get("clientInfo") or {}).get("name"),
            requested,
            version,
        )
        return {
            "protocolVersion": version,
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO,
            "instructions": instructions(user),
        }
    if method == "server/discover":
        return {
            "supportedVersions": SUPPORTED,
            "capabilities": CAPABILITIES,
            "instructions": instructions(user),
            "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tools.listing()}
    if method == "tools/call":
        return _call_tool(user, params)
    raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
