"""`hbridge ui`: a local web page for linking harnesses to providers.

The server listens on 127.0.0.1 only, and every API call must carry the
random token from the URL that `hbridge ui` prints and opens. Requests whose
Host header is not the loopback address are refused, which blocks DNS
rebinding from a web page. Keys never leave the server: the page only learns
whether a credential resolves and from which kind of source.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from hbridge import HBridgeError, __version__, credentials, tools
from hbridge.catalog import Catalog

MAX_BODY = 64 * 1024


def page_html() -> str:
    return resources.files("hbridge").joinpath("ui.html").read_text("utf-8")


def _one_shot(catalog: Catalog, tool: str, provider: str) -> str:
    spec = catalog.tool(tool)
    prefix = Path(str(spec.get("command") or spec.get("binary") or tool)).name
    names = catalog.providers.get(provider, {}).get("shim_names") or [provider]
    return f"{prefix}-{min(names, key=len)}"


def build_state(catalog: Catalog) -> dict[str, Any]:
    """Everything the page draws. Contains no secrets."""
    providers = []
    for name, spec in catalog.providers.items():
        credential = spec.get("credential")
        key_source = None
        has_key = None
        if credential:
            key, tried = credentials.resolve(catalog, credential)
            has_key = key is not None
            key_source = tried[-1] if key is not None else None
        providers.append(
            {
                "id": name,
                "label": spec.get("label") or name,
                "description": spec.get("description") or "",
                "credential": credential,
                "has_key": has_key,
                "key_source": key_source,
            }
        )

    harnesses = []
    for name in tools.configured(catalog):
        tool = tools.get(catalog, name)
        binary = tools.which(tool.spec.get("binary") or tool.name, dict(os.environ))
        entry: dict[str, Any] = {
            "id": name,
            "label": tool.spec.get("label") or name,
            "installed": binary is not None,
            "binary": binary,
            "config": str(tool.config_path()),
            "subscription": tool.spec.get("subscription"),
            "supported": list(catalog.tool_providers(name)),
            "models": {
                provider: spec.get("model")
                or (spec.get("env") or {}).get("ANTHROPIC_DEFAULT_SONNET_MODEL")
                or "tool default"
                for provider, spec in catalog.tool_providers(name).items()
            },
            "one_shots": {
                provider: _one_shot(catalog, name, provider)
                for provider in catalog.tool_providers(name)
            },
            "switch_command": tool.spec.get("switch_command")
            or {"claude": "ccuse", "codex": "cxuse", "kilo": "kuse", "pi": "piuse", "hermes": "huse"}.get(name),
            "provider": None,
            "detail": "",
            "error": None,
        }
        if binary is not None:
            try:
                status = tool.status()
                entry["provider"] = status.provider
                entry["detail"] = status.detail
            except HBridgeError as error:
                entry["error"] = str(error)
        harnesses.append(entry)
    return {
        "version": __version__,
        "catalog": catalog.sources,
        "providers": providers,
        "tools": harnesses,
    }


class UIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, catalog_path: Path | None):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(24)
        self.catalog_path = catalog_path
        self.lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?token={self.token}"

    def allowed_hosts(self) -> set[str]:
        port = self.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def catalog(self) -> Catalog:
        # Reload on every request so catalog edits show up without a restart.
        return Catalog.load(self.catalog_path)


class Handler(BaseHTTPRequestHandler):
    server: UIServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, json.dumps(value).encode(), "application/json")

    def _guard(self, *, token_in_query: bool = False) -> bool:
        if self.headers.get("Host", "") not in self.server.allowed_hosts():
            self._json(HTTPStatus.FORBIDDEN, {"error": "unexpected Host header"})
            return False
        if token_in_query:
            token = (parse_qs(urlsplit(self.path).query).get("token") or [""])[0]
        else:
            token = self.headers.get("X-HBridge-Token", "")
        if not secrets.compare_digest(token, self.server.token):
            self._json(HTTPStatus.FORBIDDEN, {"error": "missing or wrong token"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/":
            if not self._guard(token_in_query=True):
                return
            body = page_html().replace("__HBRIDGE_TOKEN__", self.server.token)
            self._send(HTTPStatus.OK, body.encode(), "text/html; charset=utf-8")
        elif path == "/api/state":
            if not self._guard():
                return
            try:
                self._json(HTTPStatus.OK, build_state(self.server.catalog()))
            except HBridgeError as error:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path != "/api/use":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._guard():
            return
        if self.headers.get_content_type() != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "expected JSON"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad request body"})
            return
        try:
            request = json.loads(self.rfile.read(length))
            tool_name, provider_name = str(request["tool"]), str(request["provider"])
        except (ValueError, KeyError, TypeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "expected {tool, provider}"})
            return
        with self.server.lock:
            try:
                catalog = self.server.catalog()
                tool = tools.get(catalog, tool_name)
                if tools.which(tool.spec.get("binary") or tool.name, dict(os.environ)) is None:
                    raise HBridgeError(f"{tool.spec.get('label') or tool.name} is not installed")
                message = tool.set(tool.resolve(provider_name))
                state = build_state(catalog)
            except HBridgeError as error:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
                return
        self._json(HTTPStatus.OK, {"message": message, "state": state})


def serve(port: int = 0, catalog_path: Path | None = None, open_browser: bool = True) -> None:
    server = UIServer(port, catalog_path)
    print(f"hbridge ui: {server.url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(server.url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
