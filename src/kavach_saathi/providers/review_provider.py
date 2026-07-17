from __future__ import annotations

import json
from pydantic import BaseModel, Field
from typing import Literal

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


SYSTEM_PROMPT = """You are Kavach Saathi's Review Integrity and Authenticity Verifier.
Your job is to run a multi-step verification of a customer review containing text and a photo of the received item.
You are given two images:
1. Image 1 (Catalogue): The official catalogue image of the product.
2. Image 2 (Review): The user's uploaded photo of the product they received.

Analyze the user's review photo against the catalogue photo and review text.
Rules:
1. product_image_match: Check if the user's photo (Image 2) shows the same product as the catalogue image (Image 1).
   - passed: True if it matches (confidence >= 60), False otherwise.
   - confidence: 0 to 100 score. If the review image is corrupted, blank, or completely unrelated to clothing (e.g. screenshot, meme), confidence MUST be < 60.
2. image_text_match: Check if the user's photo matches what they wrote in their review.
3. text_quality: Assess the quality of the review text. Classification must be one of:
   - 'relevant' (discusses quality, fit, look of the product),
   - 'unrelated' (completely different topic),
   - 'gibberish' (random chars),
   - 'lyrics_spam' (song lyrics or copypasta),
   - 'too_little_info' (e.g. single word like 'good' or 'nice' without substance, but if it has rating and minimum length check it can be considered relevant if it has context),
   - 'pot_relevant_unclear' (potentially relevant but not fully clear).
4. overall_passed: True only if product_image_match.passed is True (confidence >= 60) AND text_quality.classification is 'relevant' or 'pot_relevant_unclear'. Note: negative reviews criticizing product quality are perfectly valid; sentiment should not fail validation. Only fail if product is different, image is corrupted/unrelated, or text is spam/gibberish.
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

Compare Image 1 (Catalogue image) and Image 2 (Reviewer's uploaded photo). Evaluate text quality and overall review validity.
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
                return ReviewVerificationResult(
                    product_image_match_passed=res.product_image_match.passed,
                    product_image_match_confidence=res.product_image_match.confidence,
                    product_image_match_reason=res.product_image_match.reason,
                    image_text_match_passed=res.image_text_match.passed,
                    image_text_match_confidence=res.image_text_match.confidence,
                    image_text_match_reason=res.image_text_match.reason,
                    text_quality_passed=res.text_quality.passed,
                    text_quality_classification=res.text_quality.classification,
                    text_quality_reason=res.text_quality.reason,
                    overall_passed=res.overall_passed,
                    provider="gemini",
                    model=self.settings.gemini_reasoning_model,
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
                return ReviewVerificationResult(
                    product_image_match_passed=res.product_image_match.passed,
                    product_image_match_confidence=res.product_image_match.confidence,
                    product_image_match_reason=res.product_image_match.reason,
                    image_text_match_passed=res.image_text_match.passed,
                    image_text_match_confidence=res.image_text_match.confidence,
                    image_text_match_reason=res.image_text_match.reason,
                    text_quality_passed=res.text_quality.passed,
                    text_quality_classification=res.text_quality.classification,
                    text_quality_reason=res.text_quality.reason,
                    overall_passed=res.overall_passed,
                    provider="groq",
                    model=self.settings.groq_vision_model,
                )
            except Exception as exc:
                raise ReasoningUnavailable(f"Review verification failed on all models: {exc}") from exc

        raise ReasoningUnavailable("No review verification provider is configured")
