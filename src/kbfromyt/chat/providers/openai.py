from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from kbfromyt.chat.config import ChatConfig


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ToolCall:
    name: str
    arguments: str
    call_id: str


@dataclass
class ModelRound:
    items: list[dict] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    async def respond(
        self,
        items: list[dict],
        instructions: str,
        schema: type[BaseModel],
        tools: list[dict],
        choice: object,
    ) -> ModelRound: ...

    async def close(self) -> None: ...


class OpenAIProvider:
    def __init__(self, config: ChatConfig, client=None):
        from openai import AsyncOpenAI

        self.config = config
        self.client = client or AsyncOpenAI(
            api_key=config.api_key.get_secret_value(),
            base_url=config.base_url,
            max_retries=0,
            timeout=min(30, config.deadline),
        )

    async def respond(
        self,
        items: list[dict],
        instructions: str,
        schema: type[BaseModel],
        tools: list[dict],
        choice: object,
    ) -> ModelRound:
        import openai

        try:
            response = await self.client.responses.create(
                model=self.config.model,
                input=items,
                instructions=instructions,
                store=False,
                include=["reasoning.encrypted_content"],
                reasoning={"effort": self.config.reasoning_effort},
                max_output_tokens=self.config.max_output_tokens,
                tools=tools,
                tool_choice=choice,
                parallel_tool_calls=False,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema.__name__,
                        "strict": True,
                        "schema": schema.model_json_schema(),
                    }
                },
            )
        except openai.AuthenticationError as exc:
            raise ProviderError(
                "authentication", "OpenAI authentication failed. Check the local API key."
            ) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError(
                "permission", "The configured model or endpoint is not accessible."
            ) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(
                "rate_limit", "OpenAI rate or billing limit reached. Try again later."
            ) from exc
        except openai.NotFoundError as exc:
            raise ProviderError(
                "model_unavailable",
                "The configured model or Responses endpoint was not found. "
                "Check OPENAI_MODEL and OPENAI_BASE_URL; no substitute model was selected.",
            ) from exc
        except openai.BadRequestError as exc:
            raise ProviderError(
                "incompatible_endpoint",
                "The endpoint rejected the model, tools or structured-output contract.",
            ) from exc
        except openai.APITimeoutError as exc:
            raise ProviderError("provider_timeout", "The model request timed out.") from exc
        except openai.APIError as exc:
            raise ProviderError(
                "provider_error", "The model endpoint could not complete this request."
            ) from exc
        if response.status != "completed":
            raise ProviderError(
                "incomplete", "The model response was incomplete; no draft answer was displayed."
            )
        if any(
            c.type == "refusal"
            for item in response.output
            if item.type == "message"
            for c in item.content
        ):
            raise ProviderError(
                "refusal", "The model declined this request; no sourced answer is available."
            )
        calls = [
            ToolCall(i.name, i.arguments, i.call_id)
            for i in response.output
            if i.type == "function_call"
        ]
        usage = response.usage
        return ModelRound(
            items=[i.model_dump(mode="json", exclude_none=True) for i in response.output],
            calls=calls,
            text=response.output_text,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
        )

    async def close(self) -> None:
        await self.client.close()
