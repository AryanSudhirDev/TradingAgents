"""ChatGPT plan authorization for this locally run, open-source client.

The protocol is documented at https://developers.openai.com/siwc/token-sharing-open-source.
Credentials belong to TradingAgents, separate from Codex and API-key credentials.
"""

import base64
import contextlib
import hashlib
import json
import math
import os
import secrets
import tempfile
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

from tradingagents.dataflows.files import locked

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
_AUTH_PATH = Path.home() / ".tradingagents" / "chatgpt" / "auth.json"
_TOKEN_FIELDS = ("access_token", "refresh_token", "id_token", "expires_at", "scopes")
_INVALID_REFRESH = {
    "invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
    "refresh_token_invalidated", "refresh_token_reused",
}


class ChatGPTAuthError(ValueError):
    """Sign-in or ChatGPT plan permission needs attention."""


def _read() -> dict:
    if not _AUTH_PATH.exists():
        return {"host_id": f"urn:uuid:{uuid.uuid4()}", "profiles": {}, "active": None}
    try:
        data = json.loads(_AUTH_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data["profiles"], dict) or not data["host_id"]:
            raise ValueError
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise ChatGPTAuthError(f"Cannot read ChatGPT credentials at {_AUTH_PATH}.") from None


def _write(data: dict) -> None:
    _AUTH_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(_AUTH_PATH.parent, 0o700)
    fd, temp = tempfile.mkstemp(dir=_AUTH_PATH.parent, prefix="auth-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temp, _AUTH_PATH)
    finally:
        Path(temp).unlink(missing_ok=True)


def _post_token(values: dict) -> dict:
    try:
        response = requests.post(f"{ISSUER}/api/accounts/oauth/token", data={
            **values, "resource": RESOURCE,
        }, timeout=30, allow_redirects=False)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError
    except (requests.RequestException, ValueError):
        raise ChatGPTAuthError("ChatGPT authorization could not be reached or read; retry later.") from None
    if response.status_code != 200:
        # Provider bodies may contain credentials; expose only a recognized error code.
        code = payload.get("error")
        if isinstance(code, str) and code in _INVALID_REFRESH:
            raise ChatGPTAuthError(code)
        raise ChatGPTAuthError(f"ChatGPT authorization failed (HTTP {response.status_code}).")
    return payload


def _verify_identity(token: str, client_id: str, nonce: str | None = None) -> dict:
    try:
        import jwt
    except ImportError:
        raise ChatGPTAuthError('Install ChatGPT sign-in support: pip install ".[chatgpt]"') from None
    try:
        discovery = requests.get(f"{ISSUER}/.well-known/openid-configuration", timeout=30)
        discovery.raise_for_status()
        metadata = discovery.json()
        jwks_uri = metadata["jwks_uri"]
        if metadata["issuer"] != ISSUER or urlsplit(jwks_uri)[:2] != ("https", "auth.openai.com"):
            raise ValueError("unexpected issuer")
        key = jwt.PyJWKClient(jwks_uri, timeout=30).get_signing_key_from_jwt(token)
        identity = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id,
                              issuer=ISSUER, options={"require": ["exp", "iss", "aud", "sub"]})
        if nonce is not None and not secrets.compare_digest(identity.get("nonce", ""), nonce):
            raise ValueError("nonce mismatch")
        return identity
    except (requests.RequestException, jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise ChatGPTAuthError("ChatGPT identity verification failed; sign in again.") from None


def _credentials(payload: dict, previous: dict) -> dict:
    scopes = payload.get("scope", " ".join(previous.get("scopes", [])))
    try:
        result = {**previous, **{key: payload[key] for key in ("access_token", "refresh_token")}}
        result["scopes"] = scopes.split()
        result["expires_at"] = time.time() + float(payload["expires_in"])
        if not all(isinstance(result[k], str) and result[k] for k in ("access_token", "refresh_token")):
            raise ValueError
        if not math.isfinite(result["expires_at"]) or float(payload["expires_in"]) <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ChatGPTAuthError("ChatGPT returned incomplete credentials; sign in again.") from None
    return result


def _callback(params: dict, state: str, notify, timeout: float) -> tuple[str, dict]:
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # The callback URL carries a code; never log it.

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            valid = (parsed.path == "/auth/callback" and query.get("state") == [state])
            if valid:
                for name in ("code", "client_id", "error"):
                    values = query.get(name, [])
                    if len(values) == 1:
                        result[name] = values[0]
                result["received"] = True
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Authorization received. Return to TradingAgents." if valid else b"Invalid callback.")

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        url = f"{ISSUER}/api/accounts/authorize?{urlencode({**params, 'redirect_uri': redirect})}"
        notify(f"Continue with ChatGPT:\n{url}")
        # The printed URL also works without a graphical browser.
        with contextlib.suppress(webbrowser.Error):
            webbrowser.open(url)
        deadline = time.monotonic() + timeout
        while not result.get("received") and time.monotonic() < deadline:
            server.handle_request()
    if result.get("error") or not result.get("code"):
        raise ChatGPTAuthError("ChatGPT sign-in was declined or timed out; try again.")
    return redirect, result


def sign_in(profile_id: str | None = None, new_account: bool = False, notify=print, timeout=300) -> dict:
    """Authorize one registration, keeping existing accounts until validation succeeds."""
    # Fail before opening a browser when the optional verifier is not installed.
    try:
        import jwt  # noqa: F401
    except ImportError:
        raise ChatGPTAuthError('Install ChatGPT sign-in support: pip install ".[chatgpt]"') from None
    _AUTH_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(_AUTH_PATH):
        data = _read()
        _write(data)  # The host ID must survive even a cancelled first sign-in.
    chosen = None if new_account else (profile_id or data.get("active"))
    if chosen and chosen not in data["profiles"]:
        raise ChatGPTAuthError("Unknown ChatGPT account; list them with tradingagents chatgpt accounts.")
    previous = data["profiles"].get(chosen, {})
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": chosen or "dynamic_agent_client", "ext_agent_host_id": data["host_id"],
        "response_type": "code", "scope": SCOPE, "resource": RESOURCE,
        "state": state, "nonce": nonce, "code_challenge_method": "S256", "code_challenge": challenge,
    }
    if not chosen:
        params["agent_name_hint"] = "TradingAgents"
    redirect, callback = _callback(params, state, notify, timeout)
    client_id = callback.get("client_id") or chosen
    if not client_id or client_id == "dynamic_agent_client" or (chosen and client_id != chosen):
        raise ChatGPTAuthError("ChatGPT returned an unexpected client registration; sign in again.")
    # Retain the issued ID even if exchanging an expired code fails.
    with locked(_AUTH_PATH):
        current = _read()
        if client_id in current["profiles"]:
            previous = current["profiles"][client_id]
        current["profiles"].setdefault(client_id, {"client_id": client_id})
        _write(current)
    payload = _post_token({"grant_type": "authorization_code", "client_id": client_id,
                           "code": callback["code"], "code_verifier": verifier, "redirect_uri": redirect})
    identity = _verify_identity(payload.get("id_token", ""), client_id, nonce)
    if previous.get("subject") and previous["subject"] != identity["sub"]:
        raise ChatGPTAuthError("ChatGPT returned a different account; existing credentials were kept.")
    profile = _credentials(payload, {"client_id": client_id, "subject": identity["sub"],
                                    "email": identity.get("email", ""), "id_token": payload["id_token"]})
    with locked(_AUTH_PATH):
        current = _read()
        current["profiles"][client_id] = profile
        current["active"] = client_id
        _write(current)
    return {k: profile[k] for k in ("client_id", "email", "scopes")}


def accounts() -> list[dict]:
    """Display information only; never expose tokens to the CLI."""
    data = _read()
    return [{"client_id": key, "email": value.get("email", ""), "active": key == data.get("active")}
            for key, value in data["profiles"].items()]


def access_token() -> str:
    """Get the active grant, serializing rotating-token refreshes across runs."""
    if not _AUTH_PATH.exists():
        raise ChatGPTAuthError("Sign in first: tradingagents chatgpt login")
    with locked(_AUTH_PATH):
        data = _read()
        profile = data["profiles"].get(data.get("active"), {})
        if not profile.get("access_token"):
            raise ChatGPTAuthError("Sign in first: tradingagents chatgpt login")
        if "chatgpt.tokens.use.direct" not in profile.get("scopes", []):
            raise ChatGPTAuthError("ChatGPT plan usage was not granted. Enable it in ChatGPT settings, then sign in again.")
        if time.time() >= profile["expires_at"] - 60:
            try:
                payload = _post_token({"grant_type": "refresh_token", "client_id": profile["client_id"],
                                       "refresh_token": profile["refresh_token"]})
            except ChatGPTAuthError as exc:
                if str(exc) in _INVALID_REFRESH:
                    for key in _TOKEN_FIELDS:
                        profile.pop(key, None)
                    _write(data)
                    raise ChatGPTAuthError("ChatGPT session expired; run tradingagents chatgpt login.") from None
                raise
            updated = _credentials(payload, profile)
            if payload.get("id_token"):
                identity = _verify_identity(payload["id_token"], profile["client_id"])
                if identity["sub"] != profile["subject"]:
                    raise ChatGPTAuthError("ChatGPT refresh returned a different account; sign in again.")
                updated["id_token"] = payload["id_token"]
            data["profiles"][data["active"]] = profile = updated
            _write(data)
        if "chatgpt.tokens.use.direct" not in profile["scopes"]:
            raise ChatGPTAuthError("ChatGPT plan permission is no longer enabled; sign in again.")
        return profile["access_token"]


def list_models() -> list[tuple[str, str]]:
    try:
        response = requests.get(f"{RESOURCE}/models", headers={"Authorization": f"Bearer {access_token()}"}, timeout=30)
        response.raise_for_status()
        models = response.json()["models"]
        return [(m.get("display_name") or m["slug"], m["slug"]) for m in models if m.get("visibility") == "list"]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise ChatGPTAuthError("Could not list this ChatGPT account's models; check sign-in and retry.") from None


def sign_out() -> bool:
    """Revoke the active renewable session; keep the registration for later sign-in."""
    if not _AUTH_PATH.exists():
        return True
    with locked(_AUTH_PATH):
        data = _read()
        profile = data["profiles"].get(data.get("active"), {})
        revoked = not profile.get("refresh_token")
        if not revoked:
            try:
                response = requests.get(f"{ISSUER}/.well-known/openid-configuration", timeout=30)
                response.raise_for_status()
                endpoint = response.json()["revocation_endpoint"]
                if urlsplit(endpoint)[:2] != ("https", "auth.openai.com"):
                    raise ValueError
                revoked = requests.post(endpoint, data={"token": profile["refresh_token"],
                    "token_type_hint": "refresh_token", "client_id": profile["client_id"]},
                    timeout=30, allow_redirects=False).status_code == 200
            except (requests.RequestException, ValueError, KeyError, TypeError):
                revoked = False
        for key in _TOKEN_FIELDS:
            profile.pop(key, None)
        _write(data)
        return revoked
