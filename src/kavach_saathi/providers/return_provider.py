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

class ReturnComparisonSchema(BaseModel):
    visual_similarity_score: int = Field(ge=0, le=100)
    mismatch_detected: bool
    visible_differences: list[str]


class ReturnComparisonResult(BaseModel):
    visual_similarity_score: int
    mismatch_detected: bool
    visible_differences: list[str]
    comparison_type: Literal["front", "back"]
    provider: str
    model: str


SYSTEM_PROMPT = """You are Kavach Saathi's Return Authenticity Verifier.
Your job is to compare a reviewer/buyer's photo of a returned item against the delivery agent's photo of the delivered item.
You are given two images:
1. Image 1 (Delivered): The official photo captured when the item was delivered.
2. Image 2 (Returned): The buyer's uploaded photo of the return item.

Analyze:
1. Compare Image 1 and Image 2 carefully. They should show the same side (either both front or both back) of the same garment.
2. visual_similarity_score: Score the similarity of the two garments from 0 to 100. If they look completely identical (same fabric, pattern, color, shape), confidence is high. If there are visible mismatches (different colors, different patterns, logos, button arrangements, collar shape), confidence is low.
3. mismatch_detected: Set to True if there is a clear mismatch (e.g., visual_similarity_score < 60), False otherwise.
4. visible_differences: List specific differences observed between the two images (e.g. "Image 1 shows a red collar, Image 2 shows black", "Pattern alignment is completely different").
"""


class ReturnComparisonProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gemini = GeminiReasoningProvider(settings) if settings.gemini_api_key else None
        self.groq = GroqReasoningProvider(settings) if settings.groq_api_key else None

    async def compare(
        self,
        *,
        delivered_image_bytes: bytes,
        returned_image_bytes: bytes,
        comparison_type: Literal["front", "back"],
    ) -> ReturnComparisonResult:
        prompt = f"""Comparison Type: {comparison_type} side.
Compare Image 1 (Delivered photo) and Image 2 (Returned photo) for the {comparison_type} view of the garment.
Determine the visual similarity score, specify mismatch status, and document all visible differences.
"""
        images = [delivered_image_bytes, returned_image_bytes]

        # Gemini First
        if self.gemini:
            try:
                res = await self.gemini.structured(
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    schema=ReturnComparisonSchema,
                    images=images,
                )
                return ReturnComparisonResult(
                    visual_similarity_score=res.visual_similarity_score,
                    mismatch_detected=res.mismatch_detected,
                    visible_differences=res.visible_differences,
                    comparison_type=comparison_type,
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
                    schema=ReturnComparisonSchema,
                    images=images,
                )
                return ReturnComparisonResult(
                    visual_similarity_score=res.visual_similarity_score,
                    mismatch_detected=res.mismatch_detected,
                    visible_differences=res.visible_differences,
                    comparison_type=comparison_type,
                    provider="groq",
                    model=self.settings.groq_vision_model,
                )
            except Exception as exc:
                raise ReasoningUnavailable(f"Return comparison failed on all models: {exc}") from exc

        raise ReasoningUnavailable("No return comparison provider is configured")
