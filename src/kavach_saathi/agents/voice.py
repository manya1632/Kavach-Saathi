from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from kavach_saathi.agents.base import Agent
from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.config import get_settings
from kavach_saathi.media_storage import read_image_bytes, write_generated_image
from kavach_saathi.models import AgentName, AgentResult, Evidence, VoiceQueryRequest
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.sarvam import SarvamClient, SarvamUnavailable
from kavach_saathi.providers.vector_index import PineconeIndex, PineconeUnavailable

_AUDIO_CONTENT_TYPES = {
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mp3",
    ".m4a": "audio/mp4",
}

_SYSTEM_PROMPT = (
    "You are Kavach Saathi's universal grounded shopping experience called 'विश्वास संवाद'. Answer only from the "
    "supplied commerce evidence -- verified product specs, real buyer reviews, active page grounding data (such as orders, returns, or address info), and past "
    "resolved Q&A. Never invent discounts, delivery dates, fabric claims, or return "
    "approvals. Refuse to invent delivery dates, refunds, stock, or product claims. "
    "If multiple products are supplied, compare them using only their listed evidence. "
    "Write natural, idiomatic answers in each of English, Hindi, Bengali, Marathi, and Gujarati "
    "-- not a literal word-for-word translation of one into the others. Do NOT call yourself an agent or display an agent number."
)

_LANGUAGE_CODES = ("en", "hi", "bn", "mr", "gu")


class VoiceAnswer(BaseModel):
    answer_en: str
    answer_hi: str
    answer_bn: str
    answer_mr: str
    answer_gu: str
    confidence: int = Field(ge=0, le=100)


class VoiceQAAgent(Agent):
    """Agent 5: Grounded Voice Q&A (final target plan.md Section 6).

    RAG over Pinecone (product specs, buyer reviews, and a learning loop of past
    resolved Q&A pairs) grounds a Gemini reasoning call (the plan names Claude; Gemini
    substitutes per project notes). Sarvam AI serves real ASR/TTS. Falls back
    to deterministic keyword answers, honestly labeled, when RAG/reasoning aren't
    configured.
    """

    def __init__(self, context):
        super().__init__(context)
        settings = get_settings()
        self.index = PineconeIndex(settings, index_name=settings.pinecone_qa_index)
        self.sarvam = SarvamClient(settings)

    async def _index_product_knowledge(self, product: dict, reviews: list[dict]) -> None:
        records = [
            {
                "id": f"knowledge-{product['id']}",
                "text": (
                    f"{product['name']} ({product.get('brand', 'unknown brand')}), "
                    f"category {product['category']}, price Rs {product['price']}, "
                    f"specs: {product.get('specs', {})}, "
                    f"structured specifications: {product.get('specifications', [])}, "
                    f"size chart cm: {product.get('size_chart', {})}, "
                    f"return window {product.get('return_window_days', 7)} days, "
                    f"description: {product.get('description', '')}"
                ),
                "metadata": {"product_id": product["id"], "category": product["category"]},
            }
        ]
        for review in reviews[:10]:
            if not review.get("text") or review.get("is_hidden_by_agent"):
                continue
            records.append(
                {
                    "id": f"review-{review['id']}",
                    "text": review["text"],
                    "metadata": {"product_id": product["id"], "rating": review.get("rating", 0)},
                }
            )
        self.index.upsert(records, namespace="product_knowledge")

    async def _rag_answer(
        self,
        transcript: str,
        products: list[dict],
        buyer: dict,
        sellers: dict[str, dict],
        grounding_data: dict[str, Any],
    ) -> tuple[VoiceAnswer, dict]:
        for product in products:
            reviews = self.context.repository.product_reviews(product["id"])
            await self._index_product_knowledge(product, reviews)

        product_ids = [p["id"] for p in products]

        knowledge_matches = []
        resolved_qa_matches = []
        if product_ids:
            try:
                knowledge_matches = self.index.query(
                    transcript, namespace="product_knowledge", top_k=6, filter={"product_id": {"$in": product_ids}}
                )
                resolved_qa_matches = self.index.query(
                    transcript, namespace="resolved_qa", top_k=3, filter={"product_id": {"$in": product_ids}}
                )
            except Exception:
                pass

        grounded_products = [
            {
                "id": p["id"],
                "name": p["name"],
                "price": p["price"],
                "specs": p.get("specs", {}),
                "specifications": p.get("specifications", []),
                "size_chart_cm": p.get("size_chart", {}),
                "return_window_days": p.get("return_window_days", 7),
                "seller": sellers[p["seller_id"]],
            }
            for p in products
        ]

        grounded = {
            "question": transcript,
            "products": grounded_products,
            "retrieved_knowledge_and_reviews": knowledge_matches,
            "previously_resolved_similar_questions": resolved_qa_matches,
            "buyer_language": buyer.get("language", "hi"),
            "active_page_grounding_data": grounding_data,  # Incorporate active page grounding
        }

        if len(grounded_products) <= 20:
            answer = await self.context.reasoner.structured(
                system=_SYSTEM_PROMPT,
                prompt=f"Question: {transcript}\nEvidence: {json.dumps(grounded, ensure_ascii=False, default=str)}",
                schema=VoiceAnswer,
                reasoning_effort="low",
            )
        else:
            partial_answers = []
            for start in range(0, len(grounded_products), 20):
                chunk = grounded_products[start : start + 20]
                partial = await self.context.reasoner.structured(
                    system=_SYSTEM_PROMPT,
                    prompt=(
                        f"Compare this complete subset for: {transcript}\nProducts: "
                        f"{json.dumps(chunk, ensure_ascii=False, default=str)}"
                    ),
                    schema=VoiceAnswer,
                    reasoning_effort="low",
                )
                partial_answers.append(partial.model_dump())
            answer = await self.context.reasoner.structured(
                system=_SYSTEM_PROMPT,
                prompt=(
                    f"Synthesize the category-wide comparison for: {transcript}\n"
                    f"All product IDs: {product_ids}\nSubset answers: {json.dumps(partial_answers, ensure_ascii=False)}"
                ),
                schema=VoiceAnswer,
                reasoning_effort="low",
            )

        if product_ids:
            try:
                self.index.upsert(
                    [
                        {
                            "id": f"qa-{product_ids[0]}-{hashlib.sha1(transcript.encode()).hexdigest()[:12]}",
                            "text": transcript,
                            "metadata": {
                                "product_id": product_ids[0],
                                **{f"answer_{code}": getattr(answer, f"answer_{code}") for code in _LANGUAGE_CODES},
                            },
                        }
                    ],
                    namespace="resolved_qa",
                )
            except Exception:
                pass

        retrieved = {"knowledge_and_reviews": knowledge_matches, "resolved_qa": resolved_qa_matches}
        return answer, retrieved

    def _deterministic_answer(self, transcript: str, products: list[dict]) -> dict[str, str]:
        lower = transcript.lower()
        primary = products[0]
        specs = primary.get("specs", {})
        if len(products) > 1:
            lines = {code: [f"{p['name']}: ₹{p['price']}" for p in products] for code in _LANGUAGE_CODES}
            lines["en"] = [f"{p['name']}: Rs {p['price']}" for p in products]
            joined = {code: "; ".join(items) for code, items in lines.items()}
            comparable_details = " | ".join(
                f"{product['name']}: "
                + ", ".join(
                    f"{item['label']}={item['value']}{(' ' + item['unit']) if item.get('unit') else ''}"
                    for item in product.get("specifications", [])
                    if item.get("comparable", True)
                )
                for product in products
            )
            if comparable_details.strip(" |:"):
                joined = {code: f"{text}; {comparable_details}" for code, text in joined.items()}
            return {
                "en": "Comparing verified listings: " + joined["en"] + ".",
                "hi": "वेरिफाइड लिस्टिंग की तुलना: " + joined["hi"] + "।",
                "bn": "যাচাইকৃত তালিকার তুলনা: " + joined["bn"] + "।",
                "mr": "पडताळणी केलेल्या यादीची तुलना: " + joined["mr"] + ".",
                "gu": "ચકાસાયેલ યાદીની સરખામણી: " + joined["gu"] + ".",
            }
        if any(word in lower for word in ("fabric", "kapda", "material")):
            fabric = specs.get("fabric", "not verified")
            return {
                "en": f"The verified label lists the fabric as {fabric}.",
                "hi": f"वेरिफाइड लेबल के अनुसार इसका कपड़ा {fabric} है।",
                "bn": f"যাচাইকৃত লেবেল অনুযায়ী এর কাপড় {fabric}।",
                "mr": f"पडताळणी केलेल्या लेबलनुसार याचे कापड {fabric} आहे.",
                "gu": f"ચકાસાયેલ લેબલ મુજબ આનું કાપડ {fabric} છે.",
            }
        if any(word in lower for word in ("return", "wapas", "refund")):
            days = primary.get("return_window_days", 7)
            return {
                "en": f"This product has a {days}-day return window. Return evidence is checked fairly.",
                "hi": f"इस प्रोडक्ट पर {days} दिनों की रिटर्न विंडो है। रिटर्न एविडेंस निष्पक्ष तरीके से जाँचा जाता है।",
                "bn": f"এই পণ্যের {days} দিনের রিটার্ন উইন্ডো আছে। রিটার্ন প্রমাণ ন্যায্যভাবে পরীক্ষা করা হয়।",
                "mr": f"या उत्पादनासाठी {days} दिवसांची परतावा मुदत आहे. परतावा पुरावा निष्पक्षपणे तपासला जातो.",
                "gu": f"આ પ્રોડક્ટ માટે {days} દિવસની રિટર્ન વિન્ડો છે. રિટર્ન પુરાવો ન્યાયી રીતે તપાસવામાં આવે છે.",
            }
        return {
            "en": f"{primary['name']} costs Rs {primary['price']} and its verified details are available.",
            "hi": f"{primary['name']} की कीमत ₹{primary['price']} है; इसकी वेरिफाइड डिटेल्स उपलब्ध हैं।",
            "bn": f"{primary['name']}-এর দাম ₹{primary['price']}; এর যাচাইকৃত বিবরণ উপলব্ধ।",
            "mr": f"{primary['name']} ची किंमत ₹{primary['price']} आहे; याचा पडताळणी केलेला तपशील उपलब्ध आहे.",
            "gu": f"{primary['name']} ની કિંમત ₹{primary['price']} છે; તેની ચકાસાયેલ વિગતો ઉપલબ્ધ છે.",
        }

    async def run(self, request: VoiceQueryRequest, size_result: AgentResult | None = None) -> AgentResult:
        started_at = time.perf_counter()
        settings = get_settings()
        buyer = self.context.repository.get("buyers", request.buyer_id)
        transcript_source = "text"
        if request.text:
            transcript = request.text
        else:
            try:
                audio_bytes = await read_image_bytes(request.audio_key or "", settings)
                content_type = _AUDIO_CONTENT_TYPES.get(Path(request.audio_key or "").suffix.lower(), "audio/wav")
                transcript = await self.sarvam.transcribe(audio_bytes, request.language, content_type=content_type)
                transcript_source = "sarvam_stt"
            except (SarvamUnavailable, FileNotFoundError) as exc:
                raise RuntimeError("Voice transcription could not be completed") from exc

        # 1. Resolve active page grounding evidence
        grounding_data = {}
        products = []
        sellers = {}

        if request.page_type == "product" or request.product_id:
            try:
                prod = self.context.repository.get("products", request.product_id)
                products = [prod]
                sellers = {prod["seller_id"]: self.context.repository.get("sellers", prod["seller_id"])}
                grounding_data["product"] = {
                    "id": prod["id"],
                    "name": prod["name"],
                    "price": prod["price"],
                    "specs": prod.get("specs", {}),
                    "size_chart": prod.get("size_chart", {}),
                    "return_window_days": prod.get("return_window_days", 7),
                    "seller": sellers[prod["seller_id"]],
                }
            except Exception:
                pass

        elif request.page_type == "home":
            grounding_data["catalog_categories"] = [
                "Kurti, Saree & Lehenga",
                "Women Western",
                "Men",
                "Kids & Toys",
                "Home & Kitchen",
                "Beauty & Health",
            ]
            grounding_data["offers"] = "Free delivery on orders above Rs 499. COD available."

        elif request.page_type == "orders" and request.order_id:
            with SessionLocal() as session:
                from kavach_saathi.db.models import Order, OrderItem

                order_row = session.get(Order, request.order_id)
                # Protect order data with ownership check
                if order_row and order_row.buyer_id == request.buyer_id:
                    items = (
                        session.execute(select(OrderItem).where(OrderItem.order_id == request.order_id)).scalars().all()
                    )
                    grounding_data["order"] = {
                        "id": order_row.id,
                        "status": order_row.status,
                        "total_amount": order_row.total_amount,
                        "payment_mode": order_row.payment_mode,
                        "promised_delivery_date": order_row.promised_delivery_date.isoformat()
                        if order_row.promised_delivery_date
                        else "Not scheduled yet",
                        "items": [
                            {"product_id": it.product_id, "size": it.size, "qty": it.qty, "price": it.price_at_purchase}
                            for it in items
                        ],
                    }
                else:
                    grounding_data["order"] = "Unauthorized or order not found"

        elif request.page_type == "returns" and request.return_id:
            with SessionLocal() as session:
                from kavach_saathi.db.models import ReturnRecord

                ret_row = session.get(ReturnRecord, request.return_id)
                # Protect return data with ownership check
                if ret_row and ret_row.buyer_id == request.buyer_id:
                    grounding_data["return"] = {
                        "id": ret_row.id,
                        "order_id": ret_row.order_id,
                        "product_id": ret_row.product_id,
                        "status": ret_row.status,
                        "reason": ret_row.reason,
                        "decision": ret_row.decision,
                        "refund_status": ret_row.refund_status,
                        "next_action": "Pickup scheduled"
                        if ret_row.status == "pickup_scheduled"
                        else "Awaiting inspection/OTP confirmation",
                    }
                else:
                    grounding_data["return"] = "Unauthorized or return not found"

        elif request.page_type == "addresses":
            addresses = self.context.repository.get_user_addresses(request.buyer_id)
            grounding_data["addresses"] = [
                {
                    "city": addr.city,
                    "state": addr.state,
                    "postal_pin": addr.postal_pin,
                    "digipin": addr.digipin,
                    "validation_status": addr.validation_status,
                }
                for addr in addresses
            ]

        # 2. Get comparison products if any
        if not products and request.product_id:
            products = self.context.repository.comparison_products(
                transcript, request.product_id, request.compare_product_ids
            )
            if not products:
                try:
                    products = [self.context.repository.get("products", request.product_id)]
                except Exception:
                    pass
            sellers = {p["seller_id"]: self.context.repository.get("sellers", p["seller_id"]) for p in products}

        rag_error: str | None = None
        if size_result:
            answers = {
                code: size_result.user_message.get(code, size_result.user_message["en"]) for code in _LANGUAGE_CODES
            }
            confidence = size_result.confidence
            retrieved: dict = {}
            provider = "size_translator_handoff"
        else:
            try:
                answer, retrieved = await self._rag_answer(transcript, products, buyer, sellers, grounding_data)
                answers = {code: getattr(answer, f"answer_{code}") for code in _LANGUAGE_CODES}
                confidence = answer.confidence
                provider = f"pinecone_rag+{self.context.reasoner.name}"
            except (PineconeUnavailable, ReasoningUnavailable) as exc:
                rag_error = str(exc)
                answers = self._deterministic_answer(transcript, products)
                confidence = 94
                retrieved = {}
                provider = "deterministic_keyword_fallback"

        answer_text = answers.get(request.language, answers["en"])
        try:
            audio_bytes = await self.sarvam.synthesize(answer_text, request.language)
            audio_key = write_generated_image(
                f"generated/audio/{hashlib.sha1(answer_text.encode()).hexdigest()[:16]}.wav",
                audio_bytes,
                settings,
                content_type="audio/wav",
            )
        except SarvamUnavailable:
            audio_key = None

        result = AgentResult(
            agent=AgentName.VOICE_QA,
            confidence=confidence,
            summary=answers["en"],
            evidence=[
                Evidence(key="transcript", value=transcript, source=transcript_source),
                Evidence(key="product_ids", value=[p["id"] for p in products], source="catalogue"),
                Evidence(key="rag_context", value=retrieved, source=provider),
                Evidence(key="rag_error", value=rag_error, source="fallback_policy"),
            ],
            data={
                "transcript": transcript,
                "audio_key": audio_key,
                "language": request.language,
                "rag_error": rag_error,
            },
            user_message=answers,
        )
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="voice_qa",
                entity_type="product",
                entity_id=request.product_id or "global",
                confidence=confidence,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                input_ref=request.audio_key or transcript[:255],
                provider=provider,
                output_json=result.data,
            )
            session.commit()
        return result
