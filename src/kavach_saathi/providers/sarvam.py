from __future__ import annotations

import base64

import httpx

from kavach_saathi.config import Settings

_LANGUAGE_CODES = {
    "auto": "unknown",
    "en": "en-IN",
    "hi": "hi-IN",
    "bn": "bn-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
}

_STT_URL = "https://api.sarvam.ai/speech-to-text"
_TTS_URL = "https://api.sarvam.ai/text-to-speech"
_TTS_MAX_CHARS = 500


def _truncate_for_tts(text: str, limit: int = _TTS_MAX_CHARS) -> str:
    """Sarvam's TTS endpoint rejects any input over 500 characters. A hard slice can
    cut mid-word/mid-sentence into garbled audio, so back off to the last sentence or
    word boundary within the limit instead."""
    if len(text) <= limit:
        return text
    budget = limit - 1  # leave room for the trailing ellipsis marker
    window = text[:budget]
    for boundary in (". ", "। ", " "):
        cut = window.rfind(boundary)
        if cut > 0:
            return window[: cut + (0 if boundary == " " else 1)].rstrip() + "…"
    return window.rstrip() + "…"


class SarvamUnavailable(RuntimeError):
    pass


class SarvamClient:
    """Real Sarvam AI Speech-to-Text (Saaras) + Text-to-Speech (Bulbul) client -- the
    free-tier, self-serve substitute for the plan's named Bhashini (see project notes:
    Bhashini requires an institutional SPOC, a real blocker for an individual build).
    Config-gated on SARVAM_API_KEY; callers must catch SarvamUnavailable and fall back
    to the honest demo audio placeholder rather than fake a transcript or a voice clip.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.sarvam_api_key)

    def _headers(self) -> dict[str, str]:
        if not self.is_configured:
            raise SarvamUnavailable("SARVAM_API_KEY is not configured")
        return {"api-subscription-key": self.settings.sarvam_api_key}

    async def transcribe(self, audio_bytes: bytes, language: str, *, content_type: str = "audio/wav") -> str:
        lang_code = _LANGUAGE_CODES.get(language, "hi-IN")
        extension = content_type.split("/")[-1].split(";")[0] or "wav"
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(
                    _STT_URL,
                    headers=self._headers(),
                    data={"model": "saarika:v2.5", "language_code": lang_code},
                    files={"file": (f"audio.{extension}", audio_bytes, content_type)},
                )
                response.raise_for_status()
                transcript = response.json().get("transcript", "").strip()
                if not transcript:
                    raise SarvamUnavailable("Sarvam returned an empty transcript")
                return transcript
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise SarvamUnavailable("Sarvam speech recognition is temporarily unavailable") from exc

    async def synthesize(self, text: str, language: str) -> bytes:
        lang_code = _LANGUAGE_CODES.get(language, "hi-IN")
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(
                    _TTS_URL,
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={
                        "inputs": [_truncate_for_tts(text)],
                        "target_language_code": lang_code,
                        "speaker": "priya",
                        "model": "bulbul:v3",
                    },
                )
                response.raise_for_status()
                audio_b64 = response.json()["audios"][0]
                return base64.b64decode(audio_b64)
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            raise SarvamUnavailable("Sarvam speech synthesis is temporarily unavailable") from exc
