import base64
import hashlib
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests  # type: ignore[import-not-found]


class OAuthResult:
    def __init__(self):
        self.code: str | None = None
        self.error: str | None = None
        self.state: str | None = None
        self._event = threading.Event()

    def set(self, *, code: str | None, error: str | None, state: str | None):
        self.code = code
        self.error = error
        self.state = state
        self._event.set()

    def wait(self, timeout_s: float) -> bool:
        return self._event.wait(timeout_s)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(os.urandom(32))
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = _b64url(digest)
    return verifier, challenge


def _make_handler(result: OAuthResult, expected_state: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in ("/", "/callback"):
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            error = qs.get("error", [None])[0]
            state = qs.get("state", [None])[0]

            if state != expected_state:
                code = None
                error = error or "state_mismatch"

            result.set(code=code, error=error, state=state)

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if code:
                self.wfile.write(
                    "OK. Авторизация завершена, можно закрыть окно.".encode(
                        "utf-8",
                    )
                )
            else:
                self.wfile.write(
                    f"Ошибка авторизации: {error}".encode("utf-8"),
                )

        def log_message(self, *_args, **_kwargs):
            return

    return Handler


def yandex_start_oauth(
    *,
    client_id: str,
    scope: str | None = None,
    redirect_uri: str | None = None,
    timeout_s: float = 180.0,
) -> tuple[str, str, str, OAuthResult]:
    state = secrets.token_urlsafe(16)
    verifier, challenge = _pkce_pair()
    result = OAuthResult()

    server = None
    if redirect_uri is None:
        server = HTTPServer(("127.0.0.1", 0), _make_handler(result, state))
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/callback"
    else:
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"):
            host = "127.0.0.1"
            port = parsed.port or 80
            server = HTTPServer((host, port), _make_handler(result, state))

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "force_confirm": "yes",
    }
    if scope:
        auth_params["scope"] = scope

    auth_url = "https://oauth.yandex.com/authorize?" + urllib.parse.urlencode(
        auth_params,
    )

    if server is not None:
        def serve():
            deadline = time.time() + timeout_s
            while time.time() < deadline and not result._event.is_set():
                server.handle_request()

        t = threading.Thread(target=serve, daemon=True)
        t.start()

    return auth_url, redirect_uri, verifier, result


def yandex_exchange_code_for_token(
    *,
    client_id: str,
    code: str,
    code_verifier: str,
    client_secret: str | None = None,
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret
    else:
        data["code_verifier"] = code_verifier

    resp = requests.post(
        "https://oauth.yandex.com/token",
        data=data,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

