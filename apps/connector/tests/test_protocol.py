"""The MCP endpoint speaks both eras of the protocol, statelessly, in
plain JSON."""

import pytest

from apps.connector import protocol, tools

pytestmark = pytest.mark.django_db

MODERN = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


def test_initialize_echoes_an_older_version_it_knows(claude):
    response = claude.rpc(
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}},
    )

    result = response.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "minhome"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert "America/New_York" in result["instructions"]
    assert "Mcp-Session-Id" not in response


def test_initialize_offers_its_newest_older_version_otherwise(claude):
    result = claude.rpc("initialize", {"protocolVersion": "2026-07-28"}).json()

    assert result["result"]["protocolVersion"] == "2025-11-25"


def test_discover_lists_every_version(claude):
    result = claude.rpc("server/discover", {"_meta": MODERN}).json()["result"]

    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == protocol.SUPPORTED
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "minhome"


def test_a_header_that_disagrees_with_the_body_is_let_pass(claude):
    response = claude.rpc(
        "tools/list", {"_meta": MODERN}, HTTP_MCP_PROTOCOL_VERSION="2025-11-25"
    )

    assert response.status_code == 200
    assert response.json()["result"]["resultType"] == "complete"


def test_an_unknown_version_is_refused_with_the_known_ones(claude):
    meta = {"io.modelcontextprotocol/protocolVersion": "2030-01-01"}
    response = claude.rpc("tools/list", {"_meta": meta})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == -32022
    assert error["data"]["supported"] == protocol.SUPPORTED


def test_a_notification_is_accepted_without_an_answer(claude):
    response = claude.post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    assert response.status_code == 202
    assert response.content == b""


def test_an_unknown_method_is_not_found(claude):
    assert claude.rpc("resources/list").json()["error"]["code"] == -32601
    assert claude.rpc("resources/list", {"_meta": MODERN}).status_code == 404


def test_get_and_delete_are_not_allowed(claude):
    auth = {"HTTP_AUTHORIZATION": f"Bearer {claude.token}"}

    assert claude.client.get("/mcp", **auth).status_code == 405
    assert claude.client.delete("/mcp", **auth).status_code == 405


def test_a_foreign_origin_is_refused(claude):
    assert claude.rpc("ping", HTTP_ORIGIN="https://evil.example").status_code == 403
    assert claude.rpc("ping", HTTP_ORIGIN="https://claude.ai").status_code == 200


def test_bad_json_is_a_parse_error(claude):
    response = claude.client.post(
        "/mcp",
        "{nope",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {claude.token}",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700


def test_the_tools_are_listed_with_titles_and_hints(claude):
    listed = claude.rpc("tools/list").json()["result"]["tools"]

    assert [tool["name"] for tool in listed] == [tool["name"] for tool in tools.TOOLS]
    for tool in listed:
        assert tool["title"]
        assert tool["inputSchema"]["type"] == "object"
        assert "readOnlyHint" in tool["annotations"]
        assert "run" not in tool
    reading = {t["name"] for t in listed if t["annotations"]["readOnlyHint"]}
    assert reading == {"list_task_folders", "find_tasks", "list_events"}


def test_nothing_deletes():
    assert not [tool for tool in tools.TOOLS if "delete" in tool["name"]]


def test_an_unknown_tool_is_a_bad_call(claude):
    response = claude.rpc("tools/call", {"name": "delete_everything"})

    assert response.json()["error"]["code"] == -32602
