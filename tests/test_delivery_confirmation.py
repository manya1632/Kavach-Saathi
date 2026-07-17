from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

PLACE_CALL_TARGET = "kavach_saathi.providers.twilio_voice.TwilioVoiceClient.place_call"
IS_CONFIGURED_TARGET = "kavach_saathi.providers.twilio_voice.TwilioVoiceClient.is_configured"
DOWNLOAD_TARGET = "kavach_saathi.providers.twilio_voice.TwilioVoiceClient.download_recording"
TRANSCRIBE_TARGET = "kavach_saathi.providers.sarvam.SarvamClient.transcribe"
WHATSAPP_TARGET = "kavach_saathi.providers.twilio_voice.TwilioVoiceClient.send_whatsapp"


def _agent():
    from kavach_saathi.container import get_container

    return get_container().service.graphs.confirmation


@contextmanager
def _twilio_configured():
    """TWILIO_ACCOUNT_SID is cleared in the test environment (conftest.py), so
    is_configured is honestly False there. These tests exercise the "Twilio itself
    works, only the tunnel/phone is missing" scenarios, so is_configured is patched
    True for their duration."""
    with patch(IS_CONFIGURED_TARGET, new_callable=lambda: property(lambda self: True)):
        yield


@contextmanager
def _buyer_with_phone(agent, phone: str = "+919748572321"):
    real_get = agent.context.repository.get

    def get_with_phone(collection, record_id):
        result = real_get(collection, record_id)
        if collection == "buyers":
            result = {**result, "phone": phone}
        return result

    with patch.object(agent.context.repository, "get", side_effect=get_with_phone):
        yield


def test_initiate_call_without_twilio_configured_has_no_fallback_channel() -> None:
    """Twilio isn't configured at all in the test environment -- WhatsApp goes through
    Twilio too, so there is honestly no fallback channel available either. The agent
    must report the real failure, not silently succeed on a channel that also can't work."""
    import asyncio

    agent = _agent()

    async def run_it():
        with patch(WHATSAPP_TARGET, return_value="SMxxxx") as whatsapp_mock:
            result = await agent.initiate_call("O-GOLDEN")
            return result, whatsapp_mock

    result, whatsapp_mock = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.confidence == 0
    assert result.data["error"] is not None
    whatsapp_mock.assert_not_called()


def test_initiate_call_without_public_base_url_falls_back_to_whatsapp() -> None:
    """Twilio itself is reachable but PUBLIC_BASE_URL isn't set (the real current state
    before the tunnel is configured) -- the agent can't place a call it has nowhere to
    route webhooks for, but WhatsApp doesn't need inbound webhooks, so that fallback
    should still fire."""
    import asyncio

    agent = _agent()

    async def run_it():
        with _twilio_configured(), _buyer_with_phone(agent), patch(WHATSAPP_TARGET, return_value="SMxxxx") as wa:
            result = await agent.initiate_call("O-GOLDEN")
            return result, wa

    result, whatsapp_mock = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.confidence == 0
    assert "PUBLIC_BASE_URL" in result.data["error"]
    whatsapp_mock.assert_called_once()


def test_initiate_call_places_real_call_when_fully_configured() -> None:
    import asyncio

    from kavach_saathi.config import get_settings

    agent = _agent()
    settings = get_settings()

    async def run_it():
        with (
            patch.object(settings, "public_base_url", "https://example-tunnel.ngrok-free.app"),
            _twilio_configured(),
            _buyer_with_phone(agent),
            patch(PLACE_CALL_TARGET, return_value="CAxxxx") as call_mock,
        ):
            result = await agent.initiate_call("O-GOLDEN")
            return result, call_mock

    result, call_mock = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.confidence == 100
    assert result.data["call_sid"] == "CAxxxx"
    assert result.data["error"] is None
    call_mock.assert_called_once()
    kwargs = call_mock.call_args.kwargs
    assert kwargs["twiml_url"] == "https://example-tunnel.ngrok-free.app/v1/twilio/voice/O-GOLDEN"


def test_handle_recording_confirms_order_on_clear_yes() -> None:
    import asyncio

    from kavach_saathi.agents.confirmation import CallIntent

    agent = _agent()
    fake_intent = CallIntent(decision="confirmed", scheduled_date=None, confidence=92)

    async def run_it():
        with (
            patch(DOWNLOAD_TARGET, return_value=b"fake-wav-bytes"),
            patch(TRANSCRIBE_TARGET, return_value="Haan main ghar par hoonga"),
            patch.object(agent.context.reasoner, "structured", return_value=fake_intent),
        ):
            return await agent.handle_recording("O-GOLDEN", "https://api.twilio.com/recordings/RExxxx")

    result = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.confidence == 92
    assert result.data["intent"]["decision"] == "confirmed"

    order = agent.context.repository.get("orders", "O-GOLDEN")
    assert order["status"] == "CONFIRMED"


def test_handle_recording_falls_back_to_whatsapp_after_max_retries() -> None:
    """An unclear reply on the final allowed attempt should trigger the WhatsApp
    fallback rather than silently giving up or fabricating a decision."""
    import asyncio

    from kavach_saathi.agents.confirmation import CallIntent
    from kavach_saathi.config import get_settings
    from kavach_saathi.redis_client import get_redis

    agent = _agent()
    settings = get_settings()
    get_redis().set(agent._retry_key("O-GOLDEN"), settings.agent7_max_retries, ex=60)  # noqa: SLF001
    fake_intent = CallIntent(decision="unclear", scheduled_date=None, confidence=20)

    async def run_it():
        with (
            _twilio_configured(),
            _buyer_with_phone(agent),
            patch(DOWNLOAD_TARGET, return_value=b"fake-wav-bytes"),
            patch(TRANSCRIBE_TARGET, return_value="..."),
            patch.object(agent.context.reasoner, "structured", return_value=fake_intent),
            patch(WHATSAPP_TARGET, return_value="SMxxxx") as whatsapp_mock,
        ):
            result = await agent.handle_recording("O-GOLDEN", "https://api.twilio.com/recordings/RExxxx")
            return result, whatsapp_mock

    result, whatsapp_mock = asyncio.get_event_loop().run_until_complete(run_it())
    assert "fallback" in result.summary.lower() or "whatsapp" in result.summary.lower()
    whatsapp_mock.assert_called_once()


def test_handle_call_status_no_answer_triggers_whatsapp_fallback() -> None:
    import asyncio

    agent = _agent()

    async def run_it():
        with _twilio_configured(), _buyer_with_phone(agent), patch(WHATSAPP_TARGET, return_value="SMxxxx") as wa:
            await agent.handle_call_status("O-GOLDEN", "no-answer")
            return wa

    whatsapp_mock = asyncio.get_event_loop().run_until_complete(run_it())
    whatsapp_mock.assert_called_once()


def test_handle_call_status_completed_does_not_trigger_fallback() -> None:
    import asyncio

    agent = _agent()

    async def run_it():
        with _twilio_configured(), _buyer_with_phone(agent), patch(WHATSAPP_TARGET, return_value="SMxxxx") as wa:
            await agent.handle_call_status("O-GOLDEN", "completed")
            return wa

    whatsapp_mock = asyncio.get_event_loop().run_until_complete(run_it())
    whatsapp_mock.assert_not_called()


def test_manual_simulated_path_unchanged(client) -> None:
    """The existing checkout-flow 'confirm-simulated' endpoint stays available as a
    demo convenience alongside the new real-call path."""
    response = client.post(
        "/v1/orders/O-GOLDEN/confirm-simulated",
        json={"decision": "confirmed"},
    )
    assert response.status_code == 200
    result = response.json()["results"]["delivery_confirmation"]
    assert result["evidence"][0]["value"] == "simulated"
