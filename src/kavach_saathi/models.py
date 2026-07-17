from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class WorkflowType(StrEnum):
    LISTING = "listing"
    SIZE = "size"
    REVIEW = "review"
    REVIEW_SUMMARY = "review_summary"
    VOICE = "voice"
    ADDRESS = "address"
    RETURN = "return"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_EVIDENCE = "needs_evidence"
    MANUAL_REVIEW = "manual_review"
    RETRYABLE = "retryable"
    FAILED = "failed"


class AgentName(StrEnum):
    CATALOGUE_TRUTH = "catalogue_truth"
    SPEC_ENFORCER = "spec_enforcer"
    SIZE_TRANSLATOR = "size_translator"
    REVIEW_FILTER = "review_filter"
    VOICE_QA = "voice_qa"
    ADDRESS_GUARDIAN = "address_guardian"
    DELIVERY_CONFIRMATION = "delivery_confirmation"
    RETURN_VERIFIER = "return_verifier"


class Evidence(BaseModel):
    key: str
    value: Any
    source: str
    weight: float = Field(default=1.0, ge=0, le=1)


class AgentAction(BaseModel):
    type: str
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentName
    status: RunStatus = RunStatus.COMPLETED
    confidence: int = Field(ge=0, le=100)
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    actions: list[AgentAction] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    user_message: dict[str, str] = Field(default_factory=dict)


class RunEvent(BaseModel):
    sequence: int
    timestamp: datetime = Field(default_factory=utc_now)
    type: str
    agent: AgentName | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    workflow: WorkflowType
    status: RunStatus = RunStatus.QUEUED
    request: dict[str, Any]
    results: dict[str, AgentResult] = Field(default_factory=dict)
    events: list[RunEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    error: str | None = None


class SignupRequest(BaseModel):
    role: Literal["buyer", "seller", "delivery_boy"]
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    preferred_language: str = Field(default="en", min_length=2, max_length=8)
    email: str | None = None
    phone: str | None = None
    business_name: str | None = None

    @model_validator(mode="after")
    def require_contact(self) -> SignupRequest:
        if not self.email and not self.phone:
            raise ValueError("email or phone is required")
        return self


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, description="email or phone")
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthUser(BaseModel):
    id: str
    role: Literal["buyer", "seller", "admin", "delivery_boy"]
    name: str
    email: str | None = None
    phone: str | None = None
    preferred_language: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    user: AuthUser


class SellerSpecification(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    label: str = Field(min_length=1, max_length=120)
    value: Any
    value_type: Literal["text", "number", "percentage", "measurement", "boolean", "list"] = "text"
    unit: str | None = Field(default=None, max_length=24)
    comparison_group: str | None = Field(default=None, max_length=64)
    comparable: bool = True


class SellerSizeRow(BaseModel):
    size: str = Field(min_length=1, max_length=16)
    dimensions_cm: dict[str, float] = Field(default_factory=dict)
    stock_qty: int = Field(ge=0)
    price: float | None = Field(default=None, gt=0)


class SellerProductCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    brand: str | None = None
    description: str = ""
    category: str
    audience: str = "All"
    occasion: str | None = None
    material: str | None = None
    price: float = Field(gt=0)
    original_price: float = Field(gt=0)
    image_keys: list[str] = Field(min_length=1, max_length=5)
    seller_specs: dict[str, Any] = Field(default_factory=dict)
    specifications: list[SellerSpecification] = Field(default_factory=list, max_length=100)
    size_chart: list[SellerSizeRow] = Field(default_factory=list, max_length=30)
    stock_qty: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def unique_listing_rows(self) -> SellerProductCreate:
        spec_keys = [item.key for item in self.specifications]
        if len(spec_keys) != len(set(spec_keys)):
            raise ValueError("specification keys must be unique")
        sizes = [item.size.casefold() for item in self.size_chart]
        if len(sizes) != len(set(sizes)):
            raise ValueError("size chart sizes must be unique")
        return self


class SellerProductInitialize(BaseModel):
    product_image_keys: list[str] = Field(..., min_length=2, max_length=4)
    catalogue_image_keys: list[str] = Field(..., min_length=1, max_length=2)
    # Who Agent 1's generated "model wearing it" views should show, or "none" if
    # this product isn't a wearable garment at all (bags, footwear, jewellery, etc.).
    garment_target: Literal["woman", "man", "girl", "boy", "none"] = "woman"


class SellerProductPublish(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    brand: str | None = None
    description: str = ""
    category: str
    audience: str = "All"
    occasion: str | None = None
    material: str | None = None
    price: float = Field(gt=0)
    original_price: float = Field(gt=0)
    seller_specs: dict[str, Any] = Field(default_factory=dict)
    specifications: list[SellerSpecification] = Field(default_factory=list, max_length=100)
    size_chart: list[SellerSizeRow] = Field(default_factory=list, max_length=30)
    stock_qty: int = Field(default=0, ge=0)
    seller_corrections: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_listing_rows(self) -> SellerProductPublish:
        spec_keys = [item.key for item in self.specifications]
        if len(spec_keys) != len(set(spec_keys)):
            raise ValueError("specification keys must be unique")
        sizes = [item.size.casefold() for item in self.size_chart]
        if len(sizes) != len(set(sizes)):
            raise ValueError("size chart sizes must be unique")
        return self


class SellerProductUpdate(BaseModel):
    price: float | None = Field(default=None, gt=0)
    status: Literal["draft", "pending_seller_input", "active", "blocked", "extracting", "inconsistent"] | None = None


class SellerVariantCreate(BaseModel):
    size: str = Field(min_length=1, max_length=16)
    stock_qty: int = Field(ge=0)
    price: float | None = Field(default=None, gt=0)


class SellerOrderStatusUpdate(BaseModel):
    status: Literal["PACKED", "SHIPPED"]


class AdminReturnResolution(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str | None = None


class AdminTrustScoreOverride(BaseModel):
    trust_score: float | None = Field(default=None, ge=0, le=100)
    verified: bool | None = None


class KYCStartResponse(BaseModel):
    authorize_url: str | None
    configured: bool
    status: str


class KYCCompleteRequest(BaseModel):
    code: str
    redirect_uri: str


class Coordinates(BaseModel):
    latitude: float = Field(ge=2.5, le=38.5)
    longitude: float = Field(ge=66.0, le=99.0)


class ListingAnalyzeRequest(BaseModel):
    seller_id: str
    product_id: str
    image_keys: list[str] = Field(min_length=1, max_length=5)
    seller_specs: dict[str, Any]
    idempotency_key: str | None = None


class SizeRecommendRequest(BaseModel):
    buyer_id: str
    product_id: str
    idempotency_key: str | None = None


class ReviewAnalyzeRequest(BaseModel):
    review_id: str
    product_id: str
    image_key: str | None = None
    idempotency_key: str | None = None


class ReviewSummaryRequest(BaseModel):
    product_id: str
    idempotency_key: str | None = None


class VoiceQueryRequest(BaseModel):
    buyer_id: str
    product_id: str
    compare_product_ids: list[str] = Field(default_factory=list, max_length=100)
    text: str | None = None
    audio_key: str | None = None
    synthesize_audio: bool = False
    voice_flow: Literal["auto", "size", "general"] = "auto"
    language: str = "hi"
    page_route: str | None = None
    page_type: str | None = None
    order_id: str | None = None
    return_id: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def require_text_or_audio(self) -> VoiceQueryRequest:
        if not self.text and not self.audio_key:
            raise ValueError("Either text or audio_key is required")
        return self


class AddressVerifyRequest(BaseModel):
    buyer_id: str
    raw_address: str | None = None
    postal_pin: str = Field(pattern=r"^\d{6}$")
    coordinates: Coordinates
    idempotency_key: str | None = None

    recipient_name: str | None = None
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    locality: str | None = None
    city: str | None = None
    district: str | None = None
    state: str | None = None
    country: str | None = None
    address_type: str | None = None


class ReturnAnalyzeRequest(BaseModel):
    order_id: str
    product_id: str
    video_key: str
    additional_image_keys: list[str] = Field(default_factory=list, max_length=5)
    idempotency_key: str | None = None


class CartItemAdd(BaseModel):
    product_variant_id: str
    qty: int = Field(default=1, ge=1, le=10)


class CartItemUpdate(BaseModel):
    # Quantity zero is an intentional, atomic "remove this line" operation. Keeping
    # it on PATCH lets every quantity control use the same server-authoritative path.
    qty: int = Field(ge=0, le=10)


class OrderCreateRequest(BaseModel):
    address_id: str
    payment_mode: Literal["cod", "prepaid"]


class PaymentVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class ReviewCreateRequest(BaseModel):
    product_id: str
    order_id: str
    rating: int = Field(ge=1, le=5)
    text: str = Field(min_length=10, max_length=2000)
    image_key: str = Field(min_length=1, max_length=255)


class ReturnCreateRequest(BaseModel):
    order_id: str
    product_id: str
    reason: str = Field(min_length=3, max_length=255)
    return_type: Literal["refund", "exchange"] = "refund"


class ReturnImageAttemptRequest(BaseModel):
    front_image_key: str = Field(min_length=1, max_length=255)
    back_image_key: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PresignRequest(BaseModel):
    kind: Literal["product", "catalogue", "review", "voice", "return", "delivery"]
    filename: str
    content_type: str


class PresignResponse(BaseModel):
    object_key: str
    upload_url: HttpUrl | str
    expires_in: int


class RunEnvelope(BaseModel):
    run_id: UUID
    trace_id: UUID
    workflow: WorkflowType
    status: RunStatus
    results: dict[str, AgentResult]
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    mode: Literal["demo", "live"]
    agents: int = 8
    checks: dict[str, bool | int | str]


class AddressCreateRequest(BaseModel):
    recipient_name: str
    phone: str
    address_line1: str
    address_line2: str | None = None
    locality: str | None = None
    city: str
    district: str
    state: str
    postal_pin: str = Field(pattern=r"^\d{6}$")
    country: str = "India"
    latitude: float
    longitude: float
    address_type: str = "Home"
    is_default: bool = False
    verification_session_id: str | None = None


class AddressUpdateRequest(BaseModel):
    recipient_name: str | None = None
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    locality: str | None = None
    city: str | None = None
    district: str | None = None
    state: str | None = None
    postal_pin: str | None = Field(default=None, pattern=r"^\d{6}$")
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    address_type: str | None = None
    is_default: bool | None = None
    verification_session_id: str | None = None


class AddressGeocodeRequest(BaseModel):
    address_line1: str
    address_line2: str | None = None
    locality: str | None = None
    city: str
    district: str
    state: str
    postal_pin: str = Field(pattern=r"^\d{6}$")
    country: str = "India"


class OtpSendRequest(BaseModel):
    phone: str = Field(pattern=r"^\+?[1-9]\d{1,14}$")
    address_session_id: str = Field(min_length=16, max_length=64)


class OtpVerifyRequest(BaseModel):
    phone: str = Field(pattern=r"^\+?[1-9]\d{1,14}$")
    otp: str = Field(min_length=6, max_length=6)
    address_session_id: str = Field(min_length=16, max_length=64)


class FitFeedbackRequest(BaseModel):
    feedback: Literal["good", "tight", "loose"]


class ChatConversationCreate(BaseModel):
    page_route: str | None = None
    page_type: str | None = None
    product_id: str | None = None
    order_id: str | None = None
    return_id: str | None = None


class ChatMessageSend(BaseModel):
    conversation_id: str
    text: str = ""
    audio_key: str | None = None
    language: str = "hi"
    page_route: str | None = None
    page_type: str | None = None
    product_id: str | None = None
    order_id: str | None = None
    return_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_text_or_audio(self) -> ChatMessageSend:
        if not self.text.strip() and not self.audio_key:
            raise ValueError("Either text or audio_key is required")
        return self
