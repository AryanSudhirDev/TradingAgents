"""LangChain adapter for the official Sign in with ChatGPT Responses route."""

import logging

from langchain_openai import ChatOpenAI

from . import chatgpt_auth
from .base_client import BaseLLMClient, normalize_content
from .openai_client import NormalizedChatOpenAI

logger = logging.getLogger(__name__)

_UNSUPPORTED = {
    "background", "conversation", "max_output_tokens", "max_tool_calls", "metadata", "moderation",
    "multi_agent", "prompt", "prompt_cache_retention", "safety_identifier", "temperature",
    "top_logprobs", "top_p", "truncation", "user", "previous_response_id", "stream_options",
}


class ChatGPTChatModel(NormalizedChatOpenAI):
    def invoke(self, input, config=None, **kwargs):
        return self._remember_output(ChatOpenAI.invoke(self, input, config, **kwargs))

    async def ainvoke(self, input, config=None, **kwargs):
        return self._remember_output(await ChatOpenAI.ainvoke(self, input, config, **kwargs))

    @staticmethod
    def _remember_output(message):
        # Stateless tool turns must replay encrypted reasoning and assistant phases too.
        if isinstance(message.content, list):
            message.additional_kwargs["chatgpt_content"] = message.content
        return normalize_content(message)

    def with_structured_output(self, schema, *, method=None, **kwargs):
        method = method or "function_calling"
        if method == "function_calling":
            # Exactly one schema tool is offered inside the required namespace.
            kwargs.setdefault("tool_choice", "required")
        return super().with_structured_output(schema, method=method, **kwargs)

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        messages = [m.model_copy(update={"content": m.additional_kwargs["chatgpt_content"]})
                    if m.additional_kwargs.get("chatgpt_content") else m for m in messages]
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        for key in _UNSUPPORTED:
            payload.pop(key, None)
        payload.update(store=False, stream=True)
        for item in payload["input"]:
            if item.get("role") == "system":
                item["role"] = "developer"
            if item.get("type") in ("function_call", "function_call_output"):
                item.setdefault("namespace", "tradingagents")
        if tools := payload.get("tools"):
            if any(tool.get("type") != "function" for tool in tools):
                raise ValueError("The ChatGPT provider supports TradingAgents function tools only.")
            payload["tools"] = [{"type": "namespace", "name": "tradingagents",
                                 "description": "TradingAgents market research tools", "tools": tools}]
        return payload

    def _stream(self, *args, **kwargs):
        completed = False
        for chunk in super()._stream(*args, **kwargs):
            completed = chunk.message.response_metadata.get("status") == "completed" or completed
            yield chunk
        if not completed:
            raise ValueError("ChatGPT response did not complete; partial output was discarded.")

    async def _astream(self, *args, **kwargs):
        completed = False
        async for chunk in super()._astream(*args, **kwargs):
            completed = chunk.message.response_metadata.get("status") == "completed" or completed
            yield chunk
        if not completed:
            raise ValueError("ChatGPT response did not complete; partial output was discarded.")


class ChatGPTClient(BaseLLMClient):
    def get_llm(self):
        if self.base_url and self.base_url.rstrip("/") != chatgpt_auth.RESOURCE:
            raise ValueError("The ChatGPT provider uses https://api.openai.com/v1; remove the custom backend URL.")
        chatgpt_auth.access_token()  # Catch missing consent before the analysts start spending usage.
        options = {key: self.kwargs[key] for key in ("callbacks", "timeout", "http_client", "http_async_client",
                                                    "reasoning_effort") if key in self.kwargs}
        ignored = [key for key in ("temperature", "max_tokens") if key in self.kwargs]
        if ignored:
            logger.warning("ChatGPT plan usage does not support %s; omitted.", ", ".join(ignored))
        return ChatGPTChatModel(model=self.model, api_key=chatgpt_auth.access_token,
                                base_url=chatgpt_auth.RESOURCE, use_responses_api=True,
                                streaming=True, stream_usage=False, store=False,
                                max_retries=0, **options)

    def validate_model(self) -> bool:
        return True  # Account-specific choices come from the authenticated model catalog.
