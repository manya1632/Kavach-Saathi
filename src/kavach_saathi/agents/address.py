from __future__ import annotations

import hashlib
import hmac
import time
from typing import Literal

from pydantic import BaseModel, Field

from kavach_saathi.agents.base import Agent
from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.config import get_settings
from kavach_saathi.digipin import encode
from kavach_saathi.models import (
    AddressVerifyRequest,
    AgentAction,
    AgentName,
    AgentResult,
    Evidence,
    RunStatus,
)
from kavach_saathi.providers.google_maps import GoogleMapsGeocoder, GoogleMapsUnavailable, normalize_indic_address


class AddressValidationLLMResult(BaseModel):
    status: Literal["valid", "needs_correction"]
    confidence: int
    reason: str
    field_errors: dict[str, str] = Field(default_factory=dict)
    suggested_address: dict[str, str] = Field(default_factory=dict)


ADDRESS_VALIDATION_SYSTEM_PROMPT = """
You are the Address Guardian Agent for an e-commerce platform in India.
Your task is to validate a buyer-submitted address against reverse-geocoded data
from Google Maps at the provided coordinates.
You must check if:
1. The postal PIN code is correct for the entered city, district, and state.
2. The entered address text matches the geocoded area (within reasonable bounds,
e.g. same neighborhood/locality/city).
3. The components are mutually consistent (no major discrepancies).

If there are small spelling mistakes or slightly wrong PIN codes, you can suggest
corrections. If there are major discrepancies (e.g., entered city is Mumbai but
coordinates resolve to Bangalore), mark status as 'needs_correction'.
Provide clear, structured failure reasons in the 'reason' and 'field_errors' fields.
"""

ADDRESS_VALIDATION_PROMPT = """
Buyer Entered Address:
- Name: {recipient_name}
- Address Line 1: {address_line1}
- Address Line 2: {address_line2}
- Locality: {locality}
- City: {city}
- District: {district}
- State: {state}
- PIN Code: {postal_pin}
- Country: {country}

Google Maps Reverse Geocoded Address:
- Formatted Address: {geo_label}
- Geocoded City: {geo_city}
- Geocoded State: {geo_state}
- Geocoded PIN Code: {geo_postal_pin}

Coordinates: {latitude}, {longitude}
DIGIPIN: {digipin}

Perform the validation and output the results according to the schema.
"""


class AddressGuardianAgent(Agent):
    """Agent 6: Address Guardian. Reverse-geocodes coordinates via Google Maps
    and validates consistency with entered components using LLM structured reasoning.
    """

    def __init__(self, context):
        super().__init__(context)
        self.geocoder = GoogleMapsGeocoder(get_settings())

    async def resolve_coordinates(self, latitude: float, longitude: float) -> dict:
        """Agent tool: deterministically reverse-geocode buyer-selected coordinates."""
        return await self.geocoder.reverse_geocode(latitude, longitude)

    async def resolve_manual_address(self, address: str) -> dict:
        """Agent tool: normalize a manual address, then deterministically geocode it."""
        return await self.geocoder.geocode(normalize_indic_address(address))

    def otp_digest(self, code: str) -> str:
        """Agent tool: bind an OTP challenge to the server secret without storing plaintext."""
        return hmac.new(self.context.settings.jwt_secret.encode(), code.encode(), hashlib.sha256).hexdigest()

    def otp_matches(self, stored_digest: str, submitted_code: str) -> bool:
        """Agent tool: perform constant-time deterministic OTP verification."""
        return hmac.compare_digest(stored_digest, self.otp_digest(submitted_code))

    async def run(self, request: AddressVerifyRequest) -> AgentResult:
        started_at = time.perf_counter()
        geocode_error: str | None = None
        try:
            geo = await self.geocoder.reverse_geocode(request.coordinates.latitude, request.coordinates.longitude)
        except GoogleMapsUnavailable as exc:
            geocode_error = str(exc)
            geo = {}

        recipient_name = request.recipient_name or "Test Buyer"
        address_line1 = request.address_line1 or request.raw_address or ""
        address_line2 = request.address_line2 or ""
        locality = request.locality or ""
        city = request.city or geo.get("city", "")
        district = request.district or geo.get("city", "")
        state = request.state or geo.get("state", "")
        postal_pin = request.postal_pin
        country = request.country or "India"

        # Construct raw address text
        parts = [address_line1, address_line2, locality, city, district, state, postal_pin, country]
        raw_address_text = ", ".join([p for p in parts if p])
        normalized_address = normalize_indic_address(raw_address_text)

        # Deterministic DIGIPIN generation
        digipin = encode(request.coordinates.latitude, request.coordinates.longitude)
        expected_pin = str(geo.get("postal_pin", ""))

        # Run AI validator
        if geocode_error:
            # Address checkout is fail-closed: coordinates and structured components
            # cannot be declared consistent when the deterministic geocoder is absent.
            status = "needs_correction"
            confidence = 0
            reason = "Address could not be geocoded. Please retry before saving it."
            validation_data = {
                "status": status,
                "confidence": confidence,
                "reason": reason,
                "field_errors": {"coordinates": "Geocoding service unavailable"},
                "suggested_address": {},
            }
        else:
            try:
                # Ask the LLM reasoner to reconcile differences
                prompt_content = ADDRESS_VALIDATION_PROMPT.format(
                    recipient_name=recipient_name,
                    address_line1=address_line1,
                    address_line2=address_line2,
                    locality=locality,
                    city=city,
                    district=district,
                    state=state,
                    postal_pin=postal_pin,
                    country=country,
                    geo_label=geo.get("label", ""),
                    geo_city=geo.get("city", ""),
                    geo_state=geo.get("state", ""),
                    geo_postal_pin=geo.get("postal_pin", ""),
                    latitude=request.coordinates.latitude,
                    longitude=request.coordinates.longitude,
                    digipin=digipin,
                )

                ai_result = await self.context.reasoner.structured(
                    system=ADDRESS_VALIDATION_SYSTEM_PROMPT, prompt=prompt_content, schema=AddressValidationLLMResult
                )

                validation_data = ai_result.model_dump()
            except Exception as e:
                # Revert to deterministic PIN check if LLM fails
                pin_matches = not expected_pin or request.postal_pin == expected_pin
                validation_data = {
                    "status": "valid" if pin_matches else "needs_correction",
                    "confidence": 75 if pin_matches else 45,
                    "reason": f"Fallback check: {str(e)}",
                    "field_errors": {} if pin_matches else {"postal_pin": f"Expected PIN {expected_pin}"},
                    "suggested_address": {} if pin_matches else {"postal_pin": expected_pin},
                }

        status_val = validation_data["status"]
        confidence = validation_data["confidence"]
        reason = validation_data["reason"]

        run_status = RunStatus.COMPLETED if status_val == "valid" else RunStatus.NEEDS_EVIDENCE
        summary = f"Address is {status_val}: {reason}"

        actions = []
        if status_val == "valid":
            actions.append(AgentAction(type="confirm_address", label="Use verified address"))
        else:
            actions.append(
                AgentAction(
                    type="revise_address",
                    label="Re-verify after correction",
                    payload={
                        "suggested": validation_data["suggested_address"],
                        "errors": validation_data["field_errors"],
                    },
                )
            )

        result = AgentResult(
            agent=AgentName.ADDRESS_GUARDIAN,
            status=run_status,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(
                    key="reverse_geocode",
                    value=geo,
                    source="google_maps_geocoding_api" if not geocode_error else "unavailable",
                ),
                Evidence(key="geocode_error", value=geocode_error, source="fallback_policy"),
                Evidence(
                    key="coordinates",
                    value=request.coordinates.model_dump(),
                    source="browser_geolocation",
                ),
                Evidence(key="digipin", value=digipin, source="india_post_reference_algorithm"),
                Evidence(key="normalized_address", value=normalized_address, source="indic_nlp_normalizer"),
            ],
            actions=actions,
            data={
                "status": status_val,
                "suggested_address": validation_data["suggested_address"],
                "field_errors": validation_data["field_errors"],
                "normalized_address": normalized_address,
                "digipin": digipin,
                "postal_pin": postal_pin,
                "confidence": confidence,
                "reason": reason,
                "latitude": request.coordinates.latitude,
                "longitude": request.coordinates.longitude,
                "label": geo.get("label", ""),
                "city": geo.get("city", city),
                "district": geo.get("district", district),
                "state": geo.get("state", state),
            },
            user_message={"en": summary, "hi": f"Pata {status_val} hai: {reason}"},
        )
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="address_guardian",
                entity_type="buyer",
                entity_id=request.buyer_id,
                confidence=confidence,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                input_ref=raw_address_text,
                provider=(
                    f"google_maps+{self.context.reasoner.name}"
                    if not geocode_error
                    else "google_maps_unavailable"
                ),
                output_json=result.data,
            )
            session.commit()
        return result
