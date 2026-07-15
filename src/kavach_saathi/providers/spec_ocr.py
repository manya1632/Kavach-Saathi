from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedSpec(BaseModel):
    """Agent 2 step 1 output schema: structured spec fields extracted from a garment
    catalogue photo via the configured multimodal reasoning provider (final target
    plan.md Section 6, Agent 2). Fields that aren't visibly printed on a label must be
    left null -- the extractor is never allowed to guess a value it can't actually read.
    """

    fabric: str | None = Field(default=None, description="Fabric composition as written on the label")
    gsm: int | None = Field(default=None, description="Fabric weight in GSM if printed on the label")
    color_hex: str | None = Field(default=None, description="Best-estimate hex color of the garment")
    wash_care: str | None = Field(default=None, description="Wash care instructions as written on the label")
    dimensions_cm: str | None = Field(default=None, description="Garment dimensions in cm if printed on the label")
    label_visible: bool = Field(description="Whether a printed care label/tag was visible in the image")


EXTRACTION_SYSTEM_PROMPT = (
    "You read seller-uploaded catalogue photos for an Indian e-commerce marketplace and "
    "extract only what is actually printed on a visible care label, hang tag, or "
    "packaging. Never infer or guess a value that isn't legible in the image. If no "
    "label is visible anywhere, set label_visible=false and leave every field null."
)

EXTRACTION_PROMPT = (
    "Look at the attached catalogue photo(s) of a garment. Find any printed care "
    "label, hang tag, or packaging text and extract the fabric composition, GSM, "
    "color, wash care instructions, and dimensions exactly as printed."
)
