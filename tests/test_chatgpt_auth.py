"""Subscription credentials stay private, validated and isolated across accounts."""

import base64
import hashlib
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from tradingagents.llm_clients import chatgpt_auth as auth


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload, raise_for_status=lambda: None)


@pytest.fixture
def saved():
    profile = {"client_id": "oaiapp_one", "subject": "user-one", "email": "one@example.com",
               "access_token": "access-secret", "refresh_token": "refresh-secret", "id_token": "id-secret",
               "scopes": auth.SCOPE.split(), "expires_at": time.time() + 3600}
    store = {"host_id": "urn:uuid:host", "profiles": {"oaiapp_one": profile}, "active": "oaiapp_one"}
    auth._write(store)
    return store


def test_missing_login_never_uses_an_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "paid-key")
    with pytest.raises(auth.ChatGPTAuthError, match="chatgpt login"):
        auth.access_token()


def test_credentials_are_private_and_account_listing_contains_no_tokens(saved):
    if os.name != "nt":
        assert auth._AUTH_PATH.stat().st_mode & 0o777 == 0o600
        assert auth._AUTH_PATH.parent.stat().st_mode & 0o777 == 0o700
    assert not list(auth._AUTH_PATH.parent.glob("*.tmp"))
    assert auth.accounts() == [{"client_id": "oaiapp_one", "email": "one@example.com", "active": True}]


def test_corrupt_store_is_not_silently_replaced(saved):
    auth._AUTH_PATH.write_text("bad json")
    with pytest.raises(auth.ChatGPTAuthError, match="Cannot read"):
        auth.access_token()
    assert auth._AUTH_PATH.read_text() == "bad json"


def test_existing_access_token_needs_no_request(saved, monkeypatch):
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: pytest.fail("unexpected refresh"))
    assert auth.access_token() == "access-secret"


def test_missing_plan_permission_prevents_inference_and_refresh(saved):
    saved["profiles"][saved["active"]]["scopes"] = ["openid"]
    auth._write(saved)
    with pytest.raises(auth.ChatGPTAuthError, match="not granted"):
        auth.access_token()


def test_parallel_calls_refresh_a_rotating_token_once(saved, monkeypatch):
    saved["profiles"][saved["active"]]["expires_at"] = 0
    auth._write(saved)
    calls = []

    def refresh(url, **kwargs):
        calls.append(kwargs)
        time.sleep(0.02)
        return response({"access_token": "new-access", "refresh_token": "replacement", "expires_in": 3600})

    monkeypatch.setattr(auth.requests, "post", refresh)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: auth.access_token(), range(2))) == ["new-access"] * 2
    assert len(calls) == 1
    assert calls[0]["data"] == {"grant_type": "refresh_token", "client_id": "oaiapp_one",
                                  "refresh_token": "refresh-secret", "resource": auth.RESOURCE}
    assert auth._read()["profiles"]["oaiapp_one"]["refresh_token"] == "replacement"


@pytest.mark.parametrize("failure, cleared", [("invalid_grant", True), ("temporary", False)])
def test_only_terminal_refresh_errors_clear_credentials(saved, monkeypatch, failure, cleared):
    saved["profiles"][saved["active"]]["expires_at"] = 0
    auth._write(saved)

    def fail(*a, **k):
        raise auth.ChatGPTAuthError(failure)

    monkeypatch.setattr(auth, "_post_token", fail)
    with pytest.raises(auth.ChatGPTAuthError):
        auth.access_token()
    profile = auth._read()["profiles"]["oaiapp_one"]
    assert ("access_token" not in profile) is cleared
    assert profile["client_id"] == "oaiapp_one" and profile["subject"] == "user-one"


def test_token_endpoint_error_never_quotes_a_credential(monkeypatch):
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: response({"error": {"message": "refresh-secret"}}, 500))
    with pytest.raises(auth.ChatGPTAuthError) as error:
        auth._post_token({"refresh_token": "refresh-secret"})
    assert "refresh-secret" not in str(error.value)


def fake_login(monkeypatch, client_id="oaiapp_one", subject="user-one", **tokens):
    pytest.importorskip("jwt")
    seen = {}

    def callback(params, state, notify, timeout):
        seen.update(params)
        assert params["state"] == state
        return "http://127.0.0.1:54321/auth/callback", {"code": "code", "client_id": client_id}

    def post(values):
        expected = base64.urlsafe_b64encode(hashlib.sha256(values["code_verifier"].encode()).digest()).decode().rstrip("=")
        assert expected == seen["code_challenge"]
        assert values["client_id"] == client_id and values["redirect_uri"].endswith("/auth/callback")
        return {"access_token": "new-access", "refresh_token": "new-refresh", "id_token": "new-id",
                "expires_in": 3600, "scope": auth.SCOPE, **tokens}

    def verify(token, client, expected_nonce):
        assert expected_nonce == seen["nonce"] and token == "new-id" and client == client_id
        return {"sub": subject, "email": "one@example.com"}

    monkeypatch.setattr(auth, "_callback", callback)
    monkeypatch.setattr(auth, "_post_token", post)
    monkeypatch.setattr(auth, "_verify_identity", verify)
    return seen


def test_first_sign_in_uses_dynamic_registration_and_persists_issued_id(monkeypatch):
    seen = fake_login(monkeypatch)
    profile = auth.sign_in(notify=lambda _: None)
    store = auth._read()
    assert seen["client_id"] == "dynamic_agent_client" and seen["agent_name_hint"] == "TradingAgents"
    assert seen["ext_agent_host_id"] == store["host_id"]
    assert store["active"] == profile["client_id"] == "oaiapp_one"
    assert "new-access" not in json.dumps(profile)


def test_returning_sign_in_reuses_host_and_registration(saved, monkeypatch):
    seen = fake_login(monkeypatch)
    auth.sign_in()
    assert seen["client_id"] == "oaiapp_one" and "agent_name_hint" not in seen
    assert auth._read()["host_id"] == "urn:uuid:host"


def test_another_account_gets_its_own_registration(saved, monkeypatch):
    fake_login(monkeypatch, client_id="oaiapp_two", subject="user-two")
    auth.sign_in(new_account=True)
    store = auth._read()
    assert store["active"] == "oaiapp_two"
    assert store["profiles"]["oaiapp_one"] == saved["profiles"]["oaiapp_one"]


def test_changed_returning_client_is_refused_before_exchange(saved, monkeypatch):
    fake_login(monkeypatch, client_id="oaiapp_two")
    with pytest.raises(auth.ChatGPTAuthError, match="unexpected client"):
        auth.sign_in()
    assert auth._read() == saved


def test_changed_identity_never_replaces_existing_credentials(saved, monkeypatch):
    fake_login(monkeypatch, subject="someone-else")
    with pytest.raises(auth.ChatGPTAuthError, match="different account"):
        auth.sign_in()
    assert auth._read() == saved


def test_identity_sign_in_without_plan_permission_is_stored_but_cannot_infer(monkeypatch):
    fake_login(monkeypatch, scope="openid profile email")
    auth.sign_in()
    with pytest.raises(auth.ChatGPTAuthError, match="not granted"):
        auth.access_token()


@pytest.mark.parametrize("claim,value", [(None, None), ("nonce", "wrong"), ("aud", "wrong"), ("iss", "https://attacker.example"),
                                        ("exp", 1), ("sub", None)])
def test_signed_identity_must_match_issuer_audience_nonce_and_expiry(monkeypatch, claim, value):
    jwt = pytest.importorskip("jwt")
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = {"sub": "one", "iss": auth.ISSUER, "aud": "oaiapp_one", "nonce": "expected", "exp": time.time() + 3600}
    if claim is None:
        pass
    elif value is None:
        payload.pop(claim)
    else:
        payload[claim] = value
    token = jwt.encode(payload, key, algorithm="RS256")
    monkeypatch.setattr(auth.requests, "get", lambda *a, **k: response({"issuer": auth.ISSUER, "jwks_uri": auth.ISSUER + "/jwks"}))
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", lambda *a: SimpleNamespace(key=key.public_key()))
    if claim is None:
        assert auth._verify_identity(token, "oaiapp_one", "expected")["sub"] == "one"
    else:
        with pytest.raises(auth.ChatGPTAuthError, match="verification failed"):
            auth._verify_identity(token, "oaiapp_one", "expected")


def test_a_forged_signature_is_rejected(monkeypatch):
    jwt = pytest.importorskip("jwt")
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode({"sub": "one", "iss": auth.ISSUER, "aud": "app", "exp": time.time() + 3600}, wrong, algorithm="RS256")
    monkeypatch.setattr(auth.requests, "get", lambda *a, **k: response({"issuer": auth.ISSUER, "jwks_uri": auth.ISSUER + "/jwks"}))
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", lambda *a: SimpleNamespace(key=key.public_key()))
    with pytest.raises(auth.ChatGPTAuthError, match="verification failed"):
        auth._verify_identity(token, "app")


def test_loopback_callback_checks_state_and_path_before_accepting_code(monkeypatch):
    statuses, urls = [], []

    class Server:
        server_port, timeout = 54321, 1

        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 0)
            self.handler = handler
            self.paths = iter(["/wrong?state=expected&code=bad", "/auth/callback?state=wrong&code=bad",
                               "/auth/callback?state=expected&code=good&client_id=issued"])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def handle_request(self):
            handler = object.__new__(self.handler)
            handler.path = next(self.paths)
            handler.send_response = statuses.append
            handler.send_header = lambda *a: None
            handler.end_headers = lambda: None
            handler.wfile = io.BytesIO()
            handler.do_GET()

    monkeypatch.setattr(auth, "HTTPServer", Server)
    monkeypatch.setattr(auth.webbrowser, "open", urls.append)
    redirect, callback = auth._callback({"state": "expected"}, "expected", lambda _: None, 1)
    assert statuses == [400, 400, 200]
    assert callback["code"] == "good" and callback["client_id"] == "issued"
    assert parse_qs(urlsplit(urls[0]).query)["redirect_uri"] == [redirect]


def test_model_catalog_uses_subscription_token_and_filters_hidden_models(saved, monkeypatch):
    def get(url, **kwargs):
        assert url == auth.RESOURCE + "/models"
        assert kwargs["headers"]["Authorization"] == "Bearer access-secret"
        return response({"models": [{"slug": "allowed", "display_name": "Allowed", "visibility": "list"},
                                    {"slug": "hidden", "visibility": "hidden"}]})

    monkeypatch.setattr(auth.requests, "get", get)
    assert auth.list_models() == [("Allowed", "allowed")]


@pytest.mark.parametrize("remote_ok", [True, False])
def test_logout_clears_tokens_but_keeps_the_registration(saved, monkeypatch, remote_ok):
    monkeypatch.setattr(auth.requests, "get", lambda *a, **k: response({"revocation_endpoint": auth.ISSUER + "/revoke"}))

    def post(url, **kwargs):
        assert kwargs["data"]["token"] == "refresh-secret" and kwargs["allow_redirects"] is False
        if not remote_ok:
            raise requests.ConnectionError("offline")
        return response({}, 200)

    monkeypatch.setattr(auth.requests, "post", post)
    assert auth.sign_out() is remote_ok
    profile = auth._read()["profiles"]["oaiapp_one"]
    assert profile["subject"] == "user-one" and not any(key in profile for key in auth._TOKEN_FIELDS)
