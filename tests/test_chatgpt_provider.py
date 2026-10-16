"""Exercise the real LangChain/OpenAI wire format with an offline HTTP transport."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from typer.testing import CliRunner

import cli.main
from cli import prompts
from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating
from tradingagents.llm_clients import chatgpt_auth as auth
from tradingagents.llm_clients.factory import create_llm_client, create_tier_client


def sse(output, status="completed", error=None, terminal=True):
    result = {"id": "resp_one", "object": "response", "created_at": 1, "model": "account-model",
              "status": status, "error": error, "output": output,
              "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                        "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}
    events = [{"type": "response.created", "response": {**result, "status": "in_progress", "output": []}}]
    for index, item in enumerate(output):
        events.append({"type": "response.output_item.added", "output_index": index, "item": item})
        if item["type"] == "message":
            events.append({"type": "response.output_text.delta", "output_index": index,
                           "content_index": 0, "item_id": item["id"], "delta": item["content"][0]["text"]})
        elif item["type"] == "reasoning":
            events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    if terminal:
        events.append({"type": f"response.{status}", "response": result})
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
        f"data: {json.dumps(event)}\n\n" for event in events))


def text_output(text):
    return [{"id": "msg_one", "type": "message", "status": "completed", "role": "assistant",
             "content": [{"type": "output_text", "text": text, "annotations": []}]}]


@pytest.fixture
def make_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "paid-key-must-not-be-used")
    monkeypatch.setattr(auth, "access_token", lambda: "subscription-token")

    def make(handler, **kwargs):
        transport = httpx.MockTransport(handler)
        return create_llm_client("chatgpt", "account-model", http_client=httpx.Client(transport=transport),
                                 http_async_client=httpx.AsyncClient(transport=transport), **kwargs).get_llm()

    return make


def test_subscription_payload_and_paid_key_are_kept_separate(make_model):
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert str(request.url) == auth.RESOURCE + "/responses"
        assert request.headers["authorization"] == "Bearer subscription-token"
        assert payload["stream"] is True and payload["store"] is False
        assert payload["input"][0]["role"] == "developer"
        assert "temperature" not in payload and "max_output_tokens" not in payload
        return sse(text_output("Report."))

    model = make_model(handler, temperature=0.5, max_tokens=100)
    result = model.invoke([SystemMessage("Analyze."), HumanMessage("NVDA")])
    assert result.content == "Report." and result.usage_metadata["input_tokens"] == 10
    assert len(seen) == 1


def test_account_token_is_read_for_each_request(make_model, monkeypatch):
    tokens = []
    current = {"token": "first-token"}
    monkeypatch.setattr(auth, "access_token", lambda: current["token"])
    model = make_model(lambda r: tokens.append(r.headers["authorization"]) or sse(text_output("ok")))
    model.invoke("first")
    current["token"] = "rotated-token"
    model.invoke("second")
    assert tokens == ["Bearer first-token", "Bearer rotated-token"]


def test_namespaced_tools_and_history_round_trip(make_model):
    @tool
    def price() -> str:
        """Read the verified price."""
        return "100"

    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        namespace = payload["tools"][0]
        assert namespace["type"] == "namespace" and namespace["name"] == "tradingagents"
        assert namespace["tools"][0]["name"] == "price"
        if len(requests) == 1:
            return sse([{"type": "reasoning", "id": "rs_one", "summary": [], "encrypted_content": "encrypted-state"},
                        {"type": "function_call", "name": "price", "namespace": "tradingagents",
                         "id": "fc_one", "call_id": "call_one", "arguments": "{}", "status": "completed"}])
        reasoning = [item for item in payload["input"] if item.get("type") == "reasoning"]
        assert len(reasoning) == 1 and reasoning[0]["encrypted_content"] == "encrypted-state"
        replay = [item for item in payload["input"] if item.get("type") in ("function_call", "function_call_output")]
        assert len(replay) == 2 and all(item["namespace"] == "tradingagents" for item in replay)
        assert all(item["call_id"] == "call_one" for item in replay)
        assert payload["input"][0]["content"] == "Analyze."
        return sse(text_output("The verified price is 100."))

    model = make_model(handler).bind_tools([price])
    messages = [SystemMessage("Analyze."), HumanMessage("NVDA")]
    call = model.invoke(messages)
    assert "encrypted-state" not in call.content
    assert call.tool_calls[0]["name"] == "price" and call.tool_calls[0]["id"] == "call_one"
    answer = model.invoke([*messages, call, ToolMessage("100", tool_call_id="call_one")])
    assert answer.content == "The verified price is 100."


@pytest.mark.parametrize("asynchronous", [False, True])
def test_manager_structured_output_uses_a_namespaced_schema_tool(make_model, asynchronous):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["tools"][0]["type"] == "namespace"
        schema = payload["tools"][0]["tools"][0]
        assert schema["name"] == "PortfolioDecision" and payload["tool_choice"] == "required"
        assert "$ref" not in json.dumps(schema["parameters"])
        assert payload["stream"] is True and payload["store"] is False
        return sse([{"type": "function_call", "name": "PortfolioDecision", "namespace": "tradingagents",
                     "id": "fc_one", "call_id": "call_one", "status": "completed",
                     "arguments": json.dumps({"rating": "Overweight", "executive_summary": "Add gradually.",
                                              "investment_thesis": "Supported by the supplied reports.",
                                              "price_target": None, "time_horizon": None})}])

    model = make_model(handler).with_structured_output(PortfolioDecision)
    result = asyncio.run(model.ainvoke("Decide.")) if asynchronous else model.invoke("Decide.")
    assert isinstance(result, PortfolioDecision) and result.rating == PortfolioRating.OVERWEIGHT


@pytest.mark.parametrize("status,terminal", [("incomplete", True), ("completed", False)])
def test_incomplete_or_truncated_stream_does_not_become_a_decision(make_model, status, terminal):
    model = make_model(lambda _: sse(text_output("**Rating**: Buy"), status=status, terminal=terminal))
    with pytest.raises(ValueError, match="did not complete"):
        model.invoke("Decide.")


def test_late_usage_limit_is_an_error_not_a_partial_answer(make_model):
    error = {"code": "subscription_sharing_usage_limit_exceeded", "message": "Manage ChatGPT usage."}
    model = make_model(lambda _: sse(text_output("Partial."), status="failed", error=error))
    with pytest.raises(ValueError, match="subscription_sharing_usage_limit_exceeded"):
        model.invoke("Analyze.")


def test_async_invocation_uses_the_same_subscription_contract(make_model):
    result = asyncio.run(make_model(lambda _: sse(text_output("Async report."))).ainvoke("Analyze."))
    assert result.content == "Async report."


def test_a_custom_endpoint_cannot_receive_subscription_credentials(monkeypatch):
    monkeypatch.setattr(auth, "access_token", lambda: pytest.fail("credentials read before endpoint validation"))
    with pytest.raises(ValueError, match="remove the custom backend"):
        create_llm_client("chatgpt", "m", base_url="https://relay.example/v1").get_llm()


def test_a_tier_can_use_the_subscription(make_model, monkeypatch):
    captured = []
    from tradingagents.llm_clients import factory

    monkeypatch.setattr(factory, "create_llm_client", lambda **kw: captured.append(kw) or object())
    create_tier_client({"llm_provider": "anthropic", "backend_url": "https://other.example",
                        "deep_think_provider": "chatgpt", "deep_think_llm": "account-model",
                        "openai_reasoning_effort": "high"}, "deep")
    assert captured[0]["provider"] == "chatgpt" and captured[0]["base_url"] is None
    assert captured[0]["reasoning_effort"] == "high"


def test_cli_lists_models_and_signs_in_without_running_an_analysis(monkeypatch):
    monkeypatch.setattr(cli.main, "run_analysis", lambda **k: pytest.fail("analysis started"))
    monkeypatch.setattr(auth, "sign_in", lambda *a, **k: {"email": "one@example.com", "client_id": "app", "scopes": auth.SCOPE.split()})
    monkeypatch.setattr(auth, "list_models", lambda: [("Account Model", "model-slug")])
    runner = CliRunner()
    login = runner.invoke(cli.main.app, ["chatgpt", "login"])
    assert login.exit_code == 0 and "You're using your ChatGPT plan" in login.output
    models = runner.invoke(cli.main.app, ["chatgpt", "models"])
    assert models.exit_code == 0 and "model-slug" in models.output


def test_cli_preflight_checks_oauth_without_requesting_an_api_key(monkeypatch):
    monkeypatch.setattr(auth, "access_token", lambda: "subscription-token")
    monkeypatch.setattr(prompts.questionary, "password", lambda *a, **k: pytest.fail("API key requested"))
    assert prompts.ensure_api_key("chatgpt") is None


def test_model_picker_uses_the_active_accounts_catalog(monkeypatch):
    monkeypatch.setattr(auth, "list_models", lambda: [("Account Model", "account-model")])
    seen = []

    def select(*a, **kwargs):
        seen.extend(kwargs["choices"])
        return SimpleNamespace(ask=lambda: "account-model")

    monkeypatch.setattr(prompts.questionary, "select", select)
    assert prompts.select_deep_thinking_agent("chatgpt") == "account-model"
    assert [(choice.title, choice.value) for choice in seen] == [("Account Model", "account-model")]
