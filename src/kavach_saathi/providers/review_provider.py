from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from kavach_saathi.config import Settings
from kavach_saathi.providers.reasoning import (
    GeminiReasoningProvider,
    GroqReasoningProvider,
    ReasoningUnavailable,
)


class VerificationMatch(BaseModel):
    passed: bool
    confidence: int = Field(ge=0, le=100)
    reason: str


class TextQualityMatch(BaseModel):
    passed: bool
    classification: Literal[
        "relevant", "unrelated", "gibberish", "lyrics_spam", "too_little_info", "pot_relevant_unclear"
    ]
    reason: str


class ReviewVerificationSchema(BaseModel):
    product_image_match: VerificationMatch
    image_text_match: VerificationMatch
    text_quality: TextQualityMatch
    overall_passed: bool


class ReviewVerificationResult(BaseModel):
    product_image_match_passed: bool
    product_image_match_confidence: int
    product_image_match_reason: str
    image_text_match_passed: bool
    image_text_match_confidence: int
    image_text_match_reason: str
    text_quality_passed: bool
    text_quality_classification: str
    text_quality_reason: str
    overall_passed: bool
    provider: str
    model: str


_OPINION_WORDS = {
    "amazing",
    "average",
    "awful",
    "bad",
    "beautiful",
    "comfortable",
    "excellent",
    "good",
    "great",
    "nice",
    "poor",
    "soft",
    "stiff",
    "tight",
    "uncomfortable",
}
_GENERIC_TITLE_WORDS = {"berry", "casual", "floral", "midi", "oxford", "the", "women", "womens"}


def _has_meaningful_product_opinion(review_text: str, product_title: str) -> bool:
    """Accept concise opinions that explicitly identify the purchased product type."""
    review_words = set(re.findall(r"[a-z0-9]+", review_text.casefold()))
    title_words = set(re.findall(r"[a-z0-9]+", product_title.casefold())) - _GENERIC_TITLE_WORDS
    return bool(review_words & _OPINION_WORDS) and bool(review_words & title_words)


def _to_result(
    response: ReviewVerificationSchema,
    *,
    provider: str,
    model: str,
    product_title: str,
    review_text: str,
) -> ReviewVerificationResult:
    text_passed = response.text_quality.passed
    text_classification = response.text_quality.classification
    text_reason = response.text_quality.reason
    if (
        not text_passed
        and text_classification not in {"gibberish", "lyrics_spam"}
        and _has_meaningful_product_opinion(review_text, product_title)
    ):
        text_passed = True
        text_classification = "relevant"
        text_reason = "Concise review contains an opinion and explicitly identifies the purchased product type."

    overall_passed = (
        response.product_image_match.passed
        and response.product_image_match.confidence >= 60
        and response.image_text_match.passed
        and text_passed
    )
    return ReviewVerificationResult(
        product_image_match_passed=response.product_image_match.passed,
        product_image_match_confidence=response.product_image_match.confidence,
        product_image_match_reason=response.product_image_match.reason,
        image_text_match_passed=response.image_text_match.passed,
        image_text_match_confidence=response.image_text_match.confidence,
        image_text_match_reason=response.image_text_match.reason,
        text_quality_passed=text_passed,
        text_quality_classification=text_classification,
        text_quality_reason=text_reason,
        overall_passed=overall_passed,
        provider=provider,
        model=model,
    )


SYSTEM_PROMPT = """You are Kavach Saathi's Review Integrity and Authenticity Verifier.
Your job is to run a multi-step verification of a customer review containing text and a photo of the received item.
You are given two images:
1. Image 1 (Catalogue): The official catalogue image of the product.
2. Image 2 (Review): The user's uploaded photo of the product they received.

Analyze the user's review photo against the catalogue photo and review text.
Rules:
1. product_image_match: Check if the user's photo (Image 2) shows the same product as the catalogue image (Image 1).
   - passed: True if it matches (confidence >= 60), False otherwise.
   - confidence: 0 to 100 score. If the review image is corrupted, blank, or completely unrelated to
     clothing (e.g. screenshot, meme), confidence MUST be < 60.
2. image_text_match: Check if the user's photo matches what they wrote in their review.
3. text_quality: Assess the quality of the review text. Classification must be one of:
   - 'relevant' (discusses quality, fit, look of the product),
   - 'unrelated' (completely different topic),
   - 'gibberish' (random chars),
   - 'lyrics_spam' (song lyrics or copypasta),
   - 'too_little_info' (a single opinion word without a product reference),
   - 'pot_relevant_unclear' (potentially relevant but not fully clear).
   A concise review such as "Good shirt" is relevant when "shirt" identifies the purchased product.
   Do not reject it only for being concise.
4. overall_passed: True only if the product image matches with confidence >= 60, the image and text
   match, and text quality passes. Negative reviews criticizing product quality are valid; sentiment
   must not fail validation.
"""


class ReviewVerificationProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gemini = GeminiReasoningProvider(settings) if settings.gemini_api_key else None
        self.groq = GroqReasoningProvider(settings) if settings.groq_api_key else None

    async def verify(
        self,
        *,
        catalogue_image_bytes: bytes,
        review_image_bytes: bytes,
        product_title: str,
        product_specs: str,
        review_text: str,
    ) -> ReviewVerificationResult:
        prompt = f"""Product Title: {product_title}
Product Specifications: {product_specs}
Review Text: {review_text}

Compare Image 1 (Catalogue image) and Image 2 (Reviewer's uploaded photo).
Evaluate text quality and overall review validity.
"""
        images = [catalogue_image_bytes, review_image_bytes]

        # Gemini First
        if self.gemini:
            try:
                res = await self.gemini.structured(
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    schema=ReviewVerificationSchema,
                    images=images,
                )
                return _to_result(
                    res,
                    provider="gemini",
                    model=self.settings.gemini_reasoning_model,
                    product_title=product_title,
                    review_text=review_text,
                )
            except Exception:
                pass

        # Fallback to Groq
        if self.groq:
            try:
                res = await self.groq.structured(
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    schema=ReviewVerificationSchema,
                    images=images,
                )
                return _to_result(
                    res,
                    provider="groq",
                    model=self.settings.groq_vision_model,
                    product_title=product_title,
                    review_text=review_text,
                )
            except Exception as exc:
                raise ReasoningUnavailable(f"Review verification failed on all models: {exc}") from exc

        raise ReasoningUnavailable("No review verification provider is configured")
