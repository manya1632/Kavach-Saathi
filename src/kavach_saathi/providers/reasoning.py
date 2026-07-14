from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from kavach_saathi.config import Settings

T = TypeVar("T", bound=BaseModel)


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a pydantic JSON schema to satisfy Groq/OpenAI-style strict structured
    outputs, without touching the pydantic model it came from (which must stay
    permissive for Gemini -- see CascadingReasoningProvider's docstring). Strict mode
    requires, on every object: `additionalProperties: false`, and *every* property key
    listed in `required` (optional fields express optionality via a nullable type,
    e.g. pydantic's own `anyOf: [..., {"type": "null"}]`, not by omission from
    `required` -- omitting one, as pydantic does by convention for defaulted fields,
    is rejected by Groq's validator).
    """
    if schema.get("type") == "object" or "properties" in schema:
        schema = {**schema, "additionalProperties": False}
        if "properties" in schema:
            schema = {**schema, "required": list(schema["properties"].keys())}
    for key in ("properties", "$defs"):
        if key in schema:
            schema = {**schema, key: {k: _strict_schema(v) for k, v in schema[key].items()}}
    return schema


class ReasoningUnavailable(RuntimeError):
    """Raised when the configured reasoning provider has no usable credentials.

    Agents must treat this as an honest degradation signal (fall back to their own
    deterministic logic and say so) -- never as a reason to fabricate a result.
    """


class ReasoningProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        reasoning_effort: str = "medium",
        images: list[bytes] | None = None,
    ) -> T: ...


class DemoReasoningProvider(ReasoningProvider):
    """Rejects unplanned LLM calls in demo mode.

    Demo agents use ground-truth fixtures directly. This prevents tests from silently
    depending on a network call and keeps every scenario deterministic.
    """

    name = "demo_deterministic"

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        reasoning_effort: str = "medium",
        images: list[bytes] | None = None,
    ) -> T:
        raise ReasoningUnavailable(
            "No reasoning provider is configured (GEMINI_API_KEY/GROQ_API_KEY absent) -- "
            "agents fall back to their own deterministic logic rather than fabricate a result"
        )


class GroqReasoningProvider(ReasoningProvider):
    name = "groq"

    def __init__(self, settings: Settings):
        from groq import AsyncGroq

        self.settings = settings
        self.client = AsyncGroq(
            api_key=settings.groq_api_key,
            timeout=settings.provider_timeout_seconds,
            max_retries=0,
        )

    async def _with_rate_limit_retry(self, operation: Callable[[], Any]) -> Any:
        from groq import RateLimitError

        delay = 1.0
        for attempt in range(4):
            try:
                return await operation()
            except RateLimitError as exc:
                if attempt == 3:
                    raise
                retry_after = getattr(exc, "response", None)
                header = retry_after.headers.get("retry-after") if retry_after else None
                await asyncio.sleep(float(header or delay))
                delay *= 2
        raise RuntimeError("unreachable")

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        reasoning_effort: str = "medium",
        images: list[bytes] | None = None,
    ) -> T:
        if images:
            raise ReasoningUnavailable("Groq text models do not support image input in this integration")
        # Groq's strict JSON-schema mode requires `additionalProperties: false` on
        # every object -- but setting that via pydantic's `extra="forbid"` on the
        # model itself breaks Gemini's schema conversion (observed live: translates to
        # an unsupported `additional_properties` field in Gemini's request). Injecting
        # it into the plain schema dict here, rather than the model config, satisfies
        # both providers' opposite requirements from the same pydantic model.
        json_schema = _strict_schema(schema.model_json_schema())

        async def invoke() -> Any:
            return await self.client.chat.completions.create(
                model=self.settings.groq_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                reasoning_effort=reasoning_effort,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": json_schema,
                    },
                },
                temperature=0,
            )

        response = await self._with_rate_limit_retry(invoke)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Groq returned an empty structured response")
        return schema.model_validate(json.loads(content))


class GeminiReasoningProvider(ReasoningProvider):
    """Google Gemini as the reasoning/OCR provider (final target plan.md names Claude;
    Gemini is used here as the free-tier substitute -- see project memory/session notes
    for the reasoning). Handles both text-only reasoning (Agent 3/5/7) and multimodal
    OCR-style extraction (Agent 2) through the same interface, since Gemini 2.5 Flash
    supports both.
    """

    name = "gemini"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        if not self.settings.gemini_api_key:
            raise ReasoningUnavailable("GEMINI_API_KEY is not configured")
        from google import genai

        return genai.Client(api_key=self.settings.gemini_api_key)

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        reasoning_effort: str = "medium",
        images: list[bytes] | None = None,
    ) -> T:
        import asyncio

        # `genai.Client` has no built-in request timeout, and the blocking SDK call
        # runs on a separate OS thread via `to_thread` -- without a hard deadline here,
        # a hung Gemini request (observed in live testing: no error, just never
        # returns) blocks the caller forever with no crash and nothing to catch.
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._structured_sync, system, prompt, schema, images),
                timeout=self.settings.provider_timeout_seconds,
            )
        except TimeoutError as exc:
            timeout = self.settings.provider_timeout_seconds
            raise ReasoningUnavailable(f"Gemini request timed out after {timeout}s") from exc

    def _structured_sync(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        images: list[bytes] | None,
    ) -> T:
        from google.genai import types

        client = self._client()
        parts: list[Any] = []
        for image_bytes in images or []:
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
        parts.append(prompt)

        try:
            response = client.models.generate_content(
                model=self.settings.gemini_reasoning_model,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - normalized into a typed error the agent can catch
            raise ReasoningUnavailable(str(exc)) from exc

        if getattr(response, "parsed", None) is not None:
            return response.parsed
        if not response.text:
            raise ReasoningUnavailable("Gemini returned an empty structured response")
        return schema.model_validate(json.loads(response.text))


class CascadingReasoningProvider(ReasoningProvider):
    """Tries each configured provider in order, falling back to the next on
    ReasoningUnavailable.

    Built after live testing (Sub-phase 8) repeatedly hit Gemini's shared model
    capacity returning a transient 503 "high demand" -- a real, observed failure mode
    that a single-provider selection can't route around. Groq runs on separate
    infrastructure with a generous free tier, making it a genuine fallback rather than
    a second point of the same failure. `name` stays a fixed, honest label describing
    the whole chain (not the specific provider that happened to serve one call) since
    this instance is shared across concurrent requests and mutating it per-call would
    race.
    """

    def __init__(self, providers: list[ReasoningProvider]):
        if not providers:
            raise ValueError("CascadingReasoningProvider requires at least one provider")
        self.providers = providers
        self.name = "+".join(dict.fromkeys(p.name for p in providers))

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        reasoning_effort: str = "medium",
        images: list[bytes] | None = None,
    ) -> T:
        last_exc: ReasoningUnavailable | None = None
        for provider in self.providers:
            try:
                return await provider.structured(
                    system=system,
                    prompt=prompt,
                    schema=schema,
                    reasoning_effort=reasoning_effort,
                    images=images,
                )
            except ReasoningUnavailable as exc:
                last_exc = exc
        raise last_exc or ReasoningUnavailable("No reasoning provider is configured")
