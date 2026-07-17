from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel

from kavach_saathi.config import Settings
from kavach_saathi.providers.reasoning import (
    CascadingReasoningProvider,
    GroqReasoningProvider,
    ReasoningProvider,
    ReasoningUnavailable,
)


class _Answer(BaseModel):
    value: str


class _FakeProvider(ReasoningProvider):
    def __init__(self, name: str, *, fails: bool = False, answer: str = "ok"):
        self.name = name
        self.fails = fails
        self.answer = answer
        self.calls = 0

    async def structured(self, **kwargs) -> _Answer:
        self.calls += 1
        if self.fails:
            raise ReasoningUnavailable(f"{self.name} is down")
        return _Answer(value=self.answer)


async def _run(cascade: CascadingReasoningProvider) -> _Answer:
    return await cascade.structured(system="s", prompt="p", schema=_Answer)


def test_falls_back_to_second_provider_when_first_fails() -> None:
    import asyncio

    primary = _FakeProvider("primary", fails=True)
    backup = _FakeProvider("backup", answer="from backup")
    cascade = CascadingReasoningProvider([primary, backup])

    result = asyncio.get_event_loop().run_until_complete(_run(cascade))
    assert result.value == "from backup"
    assert primary.calls == 1
    assert backup.calls == 1


def test_uses_first_provider_when_it_succeeds_without_touching_second() -> None:
    import asyncio

    primary = _FakeProvider("primary", answer="from primary")
    backup = _FakeProvider("backup")
    cascade = CascadingReasoningProvider([primary, backup])

    result = asyncio.get_event_loop().run_until_complete(_run(cascade))
    assert result.value == "from primary"
    assert primary.calls == 1
    assert backup.calls == 0


def test_raises_when_all_providers_fail() -> None:
    import asyncio

    primary = _FakeProvider("primary", fails=True)
    backup = _FakeProvider("backup", fails=True)
    cascade = CascadingReasoningProvider([primary, backup])

    async def run_it():
        try:
            await _run(cascade)
            return None
        except ReasoningUnavailable as exc:
            return str(exc)

    error = asyncio.get_event_loop().run_until_complete(run_it())
    assert error is not None
    assert "backup" in error  # the last attempted provider's error, not the first


def test_name_describes_the_full_chain() -> None:
    cascade = CascadingReasoningProvider([_FakeProvider("gemini"), _FakeProvider("groq")])
    assert cascade.name == "gemini+groq"


def _mock_groq_response(payload: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=payload))]
    return response


def test_groq_routes_image_calls_to_the_vision_model() -> None:
    """Groq's default text model (openai/gpt-oss-120b) can't read images at all --
    when Agent 2/8 pass images, this must route to the configured vision model
    instead of the old behaviour of unconditionally raising ReasoningUnavailable
    (gap found via live testing: Gemini 503s left OCR with no working fallback)."""
    import asyncio

    settings = Settings(
        groq_api_key="test-key",
        groq_model="text-only-model",
        groq_vision_model="vision-model",
    )
    with patch("groq.AsyncGroq") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.chat.completions.create = AsyncMock(return_value=_mock_groq_response('{"value": "seen"}'))
        provider = GroqReasoningProvider(settings)

        asyncio.get_event_loop().run_until_complete(
            provider.structured(system="s", prompt="p", schema=_Answer, images=[b"fake-image-bytes"])
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "vision-model"
        user_content = call_kwargs["messages"][1]["content"]
        assert isinstance(user_content, list)
        assert user_content[1]["type"] == "image_url"
        assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_groq_uses_text_model_when_no_images() -> None:
    import asyncio

    settings = Settings(
        groq_api_key="test-key",
        groq_model="text-only-model",
        groq_vision_model="vision-model",
    )
    with patch("groq.AsyncGroq") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.chat.completions.create = AsyncMock(return_value=_mock_groq_response('{"value": "seen"}'))
        provider = GroqReasoningProvider(settings)

        asyncio.get_event_loop().run_until_complete(provider.structured(system="s", prompt="p", schema=_Answer))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "text-only-model"
        assert call_kwargs["messages"][1]["content"] == "p"
