from __future__ import annotations

import asyncio
import time
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from twilio.base.exceptions import TwilioRestException

from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.agents.base import Agent
from kavach_saathi.config import get_settings
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.media_storage import write_generated_image
from kavach_saathi.models import AgentAction, AgentName, AgentResult, Evidence
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.sarvam import SarvamClient, SarvamUnavailable
from kavach_saathi.providers.twilio_voice import TwilioUnavailable, TwilioVoiceClient
from kavach_saathi.redis_client import get_redis

_QUESTION_HI = (
    "नमस्ते! मैं कवच साथी से बोल रही हूँ। "
    "आपका ऑर्डर डिलीवरी के लिए तैयार है। "
    "क्या आप पार्सल लेने के लिए घर पर उपलब्ध होंगे? "
    "कृपया हाँ या नहीं बोलें, या रीशेड्यूल चाहिए तो बताएं।"
)
_QUESTION_EN = (
    "Hello! Your order is ready for dispatch. Will you be available at home to receive "
    "the parcel? Please say yes, no, or let us know if you'd like to reschedule."
)
_WHATSAPP_FALLBACK_HI = (
    "नमस्ते! हम आपसे कॉल पर संपर्क नहीं कर पाए। "
    "आपका ऑर्डर डिलीवरी के लिए तैयार है। "
    "कृपया इस मैसेज का जवाब दें: हाँ (घर पर होंगे), नहीं (कैंसल), या रीशेड्यूल।"
)


class CallIntent(BaseModel):
    decision: Literal["confirmed", "reschedule", "cancel", "unclear"]
    scheduled_date: str | None = None
    confidence: int = Field(ge=0, le=100)


class DeliveryConfirmationAgent(Agent):
    """Agent 7: Delivery Confirmation (final target plan.md Section 6).

    Real Twilio Programmable Voice outbound call, asking the buyer to confirm
    availability. Sarvam TTS synthesizes the question when a public URL is available to
    host the audio for Twilio's <Play>; otherwise falls back to Twilio's own <Say> --
    still a real spoken call, just not Sarvam's voice. Twilio <Record> captures the
    buyer's spoken reply, Sarvam ASR transcribes it, and Gemini classifies the intent
    (the plan names Claude; Gemini substitutes per project notes). After
    AGENT7_MAX_RETRIES unanswered/unclear attempts, falls back to a real WhatsApp
    message -- never fakes a call outcome.

    Triggered automatically on `order.placed` via the Redis Streams event bus (see
    events.py); the old `run()` simulated-decision path stays available as a manual
    checkout-flow convenience (matches the pattern already used for Agent 4's manual
    "Check review truth" button).
    """

    def __init__(self, context):
        super().__init__(context)
        settings = get_settings()
        self.twilio = TwilioVoiceClient(settings)
        self.sarvam = SarvamClient(settings)

    def _retry_key(self, order_id: str) -> str:
        return f"agent7:attempts:{order_id}"

    @staticmethod
    def _prompt_audio_key(order_id: str) -> str:
        return f"generated/audio/twilio/{order_id}-prompt.wav"

    async def pregenerate_question_audio(self, order_id: str, language: str) -> None:
        """Generate and save the Sarvam TTS prompt *before* placing the call.

        Twilio expects the /v1/twilio/voice/{order_id} webhook to answer within a few
        seconds; a live Sarvam TTS call from inside that handler is a race against
        Twilio's own timeout (observed live: a slow ~10s Sarvam response produced
        Twilio's generic "application error" mid-call). Doing the synthesis here, while
        we're still placing the call rather than answering Twilio's webhook, means the
        webhook handler only ever does a fast local file check.
        """
        settings = get_settings()
        if not settings.public_base_url:
            return
        question = _QUESTION_HI if language == "hi" else _QUESTION_EN
        try:
            audio_bytes = await self.sarvam.synthesize(question, language)
            write_generated_image(self._prompt_audio_key(order_id), audio_bytes, settings, content_type="audio/wav")
        except SarvamUnavailable:
            pass  # the webhook handler falls back to Twilio's own <Say> if no file exists

    def question_twiml_fragment(self, order_id: str, language: str) -> str:
        """Fast and synchronous -- no network calls -- safe to run inside the actual
        Twilio webhook handler, where response time directly affects the call."""
        settings = get_settings()
        question = _QUESTION_HI if language == "hi" else _QUESTION_EN
        if settings.public_base_url:
            key = self._prompt_audio_key(order_id)
            local_path = settings.asset_dir / key.removeprefix("assets/mock/")
            if local_path.exists():
                audio_url = f"{settings.public_base_url}/mock-assets/{key.removeprefix('assets/mock/')}"
                return f"<Play>{audio_url}</Play>"
        lang_tag = "hi-IN" if language == "hi" else "en-IN"
        return f'<Say language="{lang_tag}" voice="Polly.Aditi">{question}</Say>'

    def build_voice_twiml(self, order_id: str, language: str, question_fragment: str) -> str:
        settings = get_settings()
        action_url = f"{settings.public_base_url}/v1/twilio/recorded/{order_id}"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"{question_fragment}"
            f'<Record maxLength="10" playBeep="true" trim="trim-silence" action="{action_url}" method="POST" />'
            "</Response>"
        )

    async def initiate_call(self, order_id: str) -> AgentResult:
        started_at = time.perf_counter()
        settings = get_settings()
        order = self.context.repository.get("orders", order_id)
        buyer = self.context.repository.get("buyers", order["buyer_id"])
        phone = buyer.get("phone")
        language = buyer.get("language", "hi")

        error: str | None = None
        call_sid: str | None = None
        channel = "voice_call"

        if not self.twilio.is_configured:
            error = "Twilio is not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER)"
        elif not phone:
            error = "Buyer has no phone number on file"
        elif not settings.public_base_url:
            error = "PUBLIC_BASE_URL is not configured -- Twilio cannot reach webhook callbacks"
        else:
            try:
                get_redis().set(self._retry_key(order_id), 0, ex=86400)
                # Generate the prompt audio now, before placing the call, so the
                # /v1/twilio/voice/{order_id} webhook (see app.py) only ever does a
                # fast local file check when Twilio actually calls it.
                await self.pregenerate_question_audio(order_id, language)
                twiml_url = f"{settings.public_base_url}/v1/twilio/voice/{order_id}"
                status_url = f"{settings.public_base_url}/v1/twilio/status/{order_id}"
                call_sid = self.twilio.place_call(to=phone, twiml_url=twiml_url, status_callback_url=status_url)
            except (TwilioUnavailable, TwilioRestException) as exc:
                error = str(exc)[:500]

        if error:
            summary = f"Delivery confirmation call could not be placed: {error}"
            confidence = 0
            actions: list[AgentAction] = []
        else:
            summary = f"Outbound confirmation call placed to {phone}."
            confidence = 100
            actions = [
                AgentAction(
                    type="call_placed", label="Confirmation call in progress", payload={"call_sid": call_sid}
                )
            ]

        result = AgentResult(
            agent=AgentName.DELIVERY_CONFIRMATION,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(key="channel", value=channel, source="twilio_programmable_voice"),
                Evidence(key="call_sid", value=call_sid, source="twilio"),
                Evidence(key="error", value=error, source="fallback_policy"),
            ],
            actions=actions,
            data={"order_id": order_id, "call_sid": call_sid, "error": error},
            user_message={
                "en": summary,
                "hi": "Delivery confirmation call shuru ki gayi." if not error else "Call nahi ho payi.",
            },
        )

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="delivery_confirmation",
                entity_type="order",
                entity_id=order_id,
                confidence=confidence,
                latency_ms=latency_ms,
                input_ref=phone or "no_phone",
                provider="twilio" if not error else "twilio_unavailable",
                output_json=result.data,
            )
            session.commit()

        if error:
            await self._fallback_to_whatsapp(order_id, phone, language, reason=error)

        return result

    async def handle_recording(self, order_id: str, recording_url: str) -> AgentResult:
        started_at = time.perf_counter()
        settings = get_settings()
        order = self.context.repository.get("orders", order_id)
        buyer = self.context.repository.get("buyers", order["buyer_id"])
        language = buyer.get("language", "hi")

        transcript = ""
        intent: CallIntent | None = None
        error: str | None = None
        try:
            audio_bytes = await self.twilio.download_recording(recording_url)
            transcript = await self.sarvam.transcribe(audio_bytes, language, content_type="audio/wav")
            # Gemini's free tier intermittently returns a transient 503 ("high demand")
            # -- observed repeatedly in live testing even though the same call succeeds
            # moments later. Retry a couple of times before treating it as unavailable.
            last_exc: ReasoningUnavailable | None = None
            for attempt in range(3):
                try:
                    intent = await self.context.reasoner.structured(
                        system=(
                            "Classify a delivery-confirmation phone reply into exactly one intent. "
                            "Only use what the buyer actually said -- never guess a date or decision "
                            "that wasn't stated."
                        ),
                        prompt=f"Buyer's spoken reply (transcribed): {transcript!r}",
                        schema=CallIntent,
                        reasoning_effort="low",
                    )
                    break
                except ReasoningUnavailable as exc:
                    last_exc = exc
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
            else:
                raise last_exc  # noqa: B904 - re-raising the last real attempt's error, not a new one
        except (TwilioUnavailable, SarvamUnavailable, ReasoningUnavailable) as exc:
            error = str(exc)
        except (TwilioRestException, httpx.HTTPStatusError) as exc:
            # A real API-level failure downloading the recording (e.g. Twilio auth or
            # a transient error) -- log honestly rather than crash the background thread.
            error = str(exc)[:500]

        if intent and intent.decision != "unclear" and intent.confidence >= 60:
            if intent.decision == "confirmed":
                with SessionLocal() as session:
                    self.execute_delivery_transition(session, order_id, actor="agent")
                    session.commit()
            else:
                new_status = {"reschedule": "PLACED", "cancel": "CANCELLED"}[intent.decision]
                self.context.repository.update_order_status(order_id, new_status, actor="agent")
            summary = f"Buyer said: {intent.decision}" + (
                f" (reschedule to {intent.scheduled_date})" if intent.scheduled_date else ""
            )
            confidence = intent.confidence
        else:
            attempts = get_redis().incr(self._retry_key(order_id))
            if attempts <= settings.agent7_max_retries:
                summary = f"Reply unclear (attempt {attempts}); another call will be attempted."
                confidence = 30
            else:
                summary = "Reply unclear after max retries; falling back to WhatsApp."
                confidence = 20
                await self._fallback_to_whatsapp(order_id, buyer.get("phone"), language, reason="unclear_after_retries")

        result = AgentResult(
            agent=AgentName.DELIVERY_CONFIRMATION,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(key="transcript", value=transcript, source="sarvam_stt"),
                Evidence(key="intent", value=intent.model_dump() if intent else None, source="gemini_classification"),
                Evidence(key="error", value=error, source="fallback_policy"),
            ],
            actions=[],
            data={
                "order_id": order_id,
                "transcript": transcript,
                "intent": intent.model_dump() if intent else None,
                "error": error,
            },
            user_message={"en": summary, "hi": "Aapka jawaab record ho gaya."},
        )

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="delivery_confirmation",
                entity_type="order",
                entity_id=order_id,
                confidence=confidence,
                latency_ms=latency_ms,
                input_ref=recording_url,
                provider="twilio+sarvam+gemini" if not error else "degraded",
                output_json=result.data,
            )
            session.commit()
        return result

    async def handle_call_status(self, order_id: str, call_status: str) -> None:
        """Twilio's status-callback webhook: an unanswered/busy/failed call means the
        buyer never got to speak at all, so this goes straight to the WhatsApp fallback
        rather than waiting on a /recorded callback that will never arrive."""
        if call_status not in ("no-answer", "busy", "failed"):
            return
        order = self.context.repository.get("orders", order_id)
        buyer = self.context.repository.get("buyers", order["buyer_id"])
        await self._fallback_to_whatsapp(
            order_id, buyer.get("phone"), buyer.get("language", "hi"), reason=f"call_{call_status}"
        )

    async def _fallback_to_whatsapp(self, order_id: str, phone: str | None, language: str, *, reason: str) -> None:
        if not phone or not self.twilio.is_configured:
            return
        try:
            message_sid = self.twilio.send_whatsapp(to=phone, body=_WHATSAPP_FALLBACK_HI)
            provider = "twilio_whatsapp"
            error = None
        except TwilioUnavailable as exc:
            message_sid = None
            provider = "twilio_unavailable"
            error = str(exc)
        except TwilioRestException as exc:
            # A real Twilio API-level rejection (e.g. the recipient hasn't joined the
            # WhatsApp sandbox yet) -- a genuine failure to log honestly, not a crash.
            message_sid = None
            provider = "twilio_api_error"
            error = str(exc)[:500]
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="delivery_confirmation",
                entity_type="order",
                entity_id=order_id,
                confidence=100 if message_sid else 0,
                latency_ms=0,
                input_ref=f"reason={reason}",
                provider=provider,
                output_json={"message_sid": message_sid, "reason": reason, "error": error},
            )
            session.commit()

    def execute_delivery_transition(self, session: SessionLocal, order_id: str, actor: str = "agent") -> None:
        from datetime import UTC, datetime

        from kavach_saathi.db.models import Order, OrderItem, OrderStatusHistory, Product, ProductVariant
        from kavach_saathi.order_status import OrderStatus

        order = session.query(Order).filter(Order.id == order_id).with_for_update().first()
        if not order:
            return

        statuses = [
            OrderStatus.CONFIRMED,
            OrderStatus.PACKED,
            OrderStatus.SHIPPED,
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.DELIVERED,
        ]

        for status in statuses:
            already_done = session.query(OrderStatusHistory).filter(
                OrderStatusHistory.order_id == order_id,
                OrderStatusHistory.status == status
            ).first()
            if not already_done:
                order.status = status
                order.updated_at = datetime.now(UTC)
                session.add(OrderStatusHistory(order_id=order_id, status=status, actor=actor))
                session.flush()

                if status == OrderStatus.DELIVERED:
                    if not order.stock_decremented:
                        items = session.query(OrderItem).filter(OrderItem.order_id == order_id).all()
                        variant_ids = [item.product_variant_id for item in items if item.product_variant_id]
                        locked_variants = {}
                        if variant_ids:
                            locked_variants = {
                                v.id: v for v in session.query(ProductVariant)
                                .filter(ProductVariant.id.in_(variant_ids))
                                .with_for_update()
                                .all()
                            }
                        for item in items:
                            if item.product_variant_id:
                                variant = locked_variants.get(item.product_variant_id)
                                if variant:
                                    variant.stock_qty = max(0, variant.stock_qty - item.qty)
                                    product = (
                                        session.query(Product)
                                        .filter(Product.id == item.product_id)
                                        .with_for_update()
                                        .first()
                                    )
                                    if product:
                                        product.stock = max(0, product.stock - item.qty)
                            else:
                                product = (
                                    session.query(Product)
                                    .filter(Product.id == item.product_id)
                                    .with_for_update()
                                    .first()
                                )
                                if product:
                                    product.stock = max(0, product.stock - item.qty)
                        order.stock_decremented = True
                        session.flush()
