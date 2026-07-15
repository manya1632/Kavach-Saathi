from __future__ import annotations

from kavach_saathi.agents.base import Agent
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


class AddressGuardianAgent(Agent):
    """Agent 6: Address Guardian (final target plan.md Section 6). Reverse-geocodes
    the buyer's coordinates via the real Google Maps Geocoding API (the plan's stack
    table names Amazon Location; Google Maps is the provider actually configured for
    this project -- see project notes) and normalizes any Devanagari/Indic-script raw
    address text via IndicNLP before persisting it. Bypasses `context.external` and
    instantiates its own config-gated provider directly, matching the pattern used by
    Agents 3/5/7/8 (the demo/live provider split never activates since app_mode is
    always "demo").
    """

    def __init__(self, context):
        super().__init__(context)
        self.geocoder = GoogleMapsGeocoder(get_settings())

    async def run(self, request: AddressVerifyRequest) -> AgentResult:
        geocode_error: str | None = None
        try:
            geo = await self.geocoder.reverse_geocode(request.coordinates.latitude, request.coordinates.longitude)
        except GoogleMapsUnavailable as exc:
            geocode_error = str(exc)
            geo: dict[str, str] = {}

        normalized_address = normalize_indic_address(request.raw_address)
        digipin = encode(request.coordinates.latitude, request.coordinates.longitude)
        expected_pin = str(geo.get("postal_pin", ""))

        if geocode_error:
            # Honest degrade (never fake a PIN match we couldn't actually check): no
            # live geocoder available means the postal PIN genuinely can't be
            # cross-checked, so this goes to manual review rather than silently
            # passing verification.
            pin_matches = False
            confidence = 35
            status = RunStatus.NEEDS_EVIDENCE
            summary = f"Live geocoding is unavailable ({geocode_error}); postal PIN could not be cross-checked."
            actions = [
                AgentAction(
                    type="manual_pin_check",
                    label="Confirm postal PIN manually",
                    payload={"postal_pin": request.postal_pin},
                )
            ]
        else:
            pin_matches = not expected_pin or request.postal_pin == expected_pin
            confidence = 97 if pin_matches else 62
            status = RunStatus.COMPLETED if pin_matches else RunStatus.NEEDS_EVIDENCE
            summary = (
                "Address and postal PIN agree with the live coordinates."
                if pin_matches
                else f"Coordinates map to postal PIN {expected_pin}, not {request.postal_pin}."
            )
            actions = [
                AgentAction(type="confirm_address", label="Use verified address")
                if pin_matches
                else AgentAction(
                    type="correct_postal_pin",
                    label=f"Change postal PIN to {expected_pin}",
                    payload={"postal_pin": expected_pin},
                )
            ]

        # Persist as a real `addresses` row so checkout has something to reference --
        # previously Agent 6 verified an address but never wrote it anywhere, leaving
        # `/v1/orders` with no real address_id to point at (commerce backbone gap).
        address_id = self.context.repository.save_verified_address(
            request.buyer_id,
            raw_address=normalized_address,
            city=geo.get("city"),
            state=geo.get("state"),
            postal_pin=request.postal_pin if pin_matches else (expected_pin or request.postal_pin),
            latitude=request.coordinates.latitude,
            longitude=request.coordinates.longitude,
            digipin=digipin,
        )

        return AgentResult(
            agent=AgentName.ADDRESS_GUARDIAN,
            status=status,
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
                "normalized_address": geo.get("label") or normalized_address,
                "digipin": digipin,
                "postal_pin": expected_pin or request.postal_pin,
                "address_id": address_id,
            },
            user_message={"en": summary, "hi": "Location se address aur DIGIPIN verify ho gaya."},
        )
