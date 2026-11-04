import http.client
import json
import threading

import pytest

from hbridge import ui
from hbridge.catalog import Catalog


@pytest.fixture
def server(home):
    srv = ui.UIServer(0, None)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, method, path, *, body=None, token=True, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    headers = {"Host": host or f"127.0.0.1:{srv.server_address[1]}"}
    if token:
        headers["X-HBridge-Token"] = srv.token
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body)
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def test_state_marks_installed_and_missing(home, monkeypatch):
    (home / "bin" / "kilo").unlink()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret")
    state = ui.build_state(Catalog.load())
    by_id = {t["id"]: t for t in state["tools"]}
    assert by_id["kilo"]["installed"] is False
    assert by_id["claude"]["installed"] is True
    assert by_id["claude"]["provider"] == "anthropic"
    assert by_id["codex"]["supported"] == ["openai", "go", "openrouter"]
    assert by_id["codex"]["one_shots"]["openrouter"] == "codex-or"
    assert by_id["codex"]["switch_command"] == "cxuse"
    providers = {p["id"]: p for p in state["providers"]}
    assert providers["openrouter"]["has_key"] is True
    assert providers["go"]["has_key"] is False
    assert providers["anthropic"]["has_key"] is None
    # Keys never reach the page.
    assert "or-secret" not in json.dumps(state)


def test_page_requires_token(server):
    status, _ = request(server, "GET", "/", token=False)
    assert status == 403
    status, body = request(server, "GET", f"/?token={server.token}", token=False)
    assert status == 200
    assert server.token.encode() in body
    assert b"__HBRIDGE_TOKEN__" not in body


def test_api_rejects_missing_token_and_foreign_host(server):
    assert request(server, "GET", "/api/state", token=False)[0] == 403
    assert request(server, "GET", "/api/state", host="evil.example:80")[0] == 403
    status, body = request(server, "GET", "/api/state")
    assert status == 200
    assert {t["id"] for t in json.loads(body)["tools"]} == {"claude", "codex", "kilo", "pi", "hermes"}


def test_use_switches_and_returns_state(server, home):
    status, body = request(server, "POST", "/api/use", body={"tool": "codex", "provider": "go"})
    assert status == 200, body
    result = json.loads(body)
    assert result["message"].startswith("codex: go")
    codex = next(t for t in result["state"]["tools"] if t["id"] == "codex")
    assert codex["provider"] == "go"
    assert 'model_provider = "opencode_go"' in (home / ".codex/config.toml").read_text()


def test_use_errors(server, home):
    status, body = request(server, "POST", "/api/use", body={"tool": "claude", "provider": "openai"})
    assert status == 422
    assert "unknown provider" in json.loads(body)["error"]
    (home / "bin" / "pi").unlink()
    status, body = request(server, "POST", "/api/use", body={"tool": "pi", "provider": "go"})
    assert status == 422
    assert "not installed" in json.loads(body)["error"]
    status, _ = request(server, "POST", "/api/use", body={"oops": 1})
    assert status == 400
    assert request(server, "POST", "/api/use", body={"tool": "codex", "provider": "go"}, token=False)[0] == 403
