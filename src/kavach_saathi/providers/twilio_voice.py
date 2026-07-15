from __future__ import annotations

import asyncio

import httpx

from kavach_saathi.config import Settings


class TwilioUnavailable(RuntimeError):
    pass


class TwilioVoiceClient:
    """Real Twilio Programmable Voice + WhatsApp client (final target plan.md Agent 7).

    Places a genuine outbound phone call, and can fall back to a real WhatsApp message
    when the call goes unanswered or fails after retries. Config-gated on
    TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER; callers must catch TwilioUnavailable and
    degrade honestly rather than fake a call outcome.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.twilio_account_sid
            and self.settings.twilio_auth_token
            and self.settings.twilio_from_number
        )

    def _client(self):
        if not self.is_configured:
            raise TwilioUnavailable("TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER are not fully configured")
        from twilio.rest import Client

        return Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)

    def place_call(self, *, to: str, twiml_url: str, status_callback_url: str) -> str:
        client = self._client()
        call = client.calls.create(
            to=to,
            from_=self.settings.twilio_from_number,
            url=twiml_url,
            status_callback=status_callback_url,
            status_callback_event=["completed", "no-answer", "busy", "failed"],
            status_callback_method="POST",
        )
        return call.sid

    async def download_recording(self, recording_url: str, *, retries: int = 3) -> bytes:
        """Twilio's recording webhooks give a base URL without a media extension;
        appending `.wav` requests the WAV rendering, and the download itself requires
        Basic Auth with the same account credentials used to place the call.

        Twilio's `/recorded` webhook can fire a moment before the recording media is
        actually ready to serve (a 404 in that brief window is not "the recording is
        gone", it's "not encoded yet") -- retry with a short backoff rather than treat
        that race as a hard failure.
        """
        if not self.is_configured:
            raise TwilioUnavailable("TWILIO_ACCOUNT_SID/AUTH_TOKEN are not configured")
        last_exc: httpx.HTTPStatusError | None = None
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            for attempt in range(retries):
                response = await client.get(
                    f"{recording_url}.wav",
                    auth=(self.settings.twilio_account_sid, self.settings.twilio_auth_token),
                )
                if response.status_code == 404 and attempt < retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    break
                return response.content
        raise last_exc or TwilioUnavailable("Recording download failed with no response")

    def send_whatsapp(self, *, to: str, body: str) -> str:
        client = self._client()
        message = client.messages.create(
            from_=self.settings.twilio_whatsapp_from,
            to=f"whatsapp:{to}",
            body=body,
        )
        return message.sid
