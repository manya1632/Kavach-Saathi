from __future__ import annotations

from kavach_saathi.agents.base import Agent
from kavach_saathi.digipin import encode
from kavach_saathi.models import (
    AddressVerifyRequest,
    AgentAction,
    AgentName,
    AgentResult,
    Evidence,
    RunStatus,
)


class AddressGuardianAgent(Agent):
    async def run(self, request: AddressVerifyRequest) -> AgentResult:
        geo = await self.context.external.reverse_geocode(request.coordinates.latitude, request.coordinates.longitude)
        digipin = encode(request.coordinates.latitude, request.coordinates.longitude)
        expected_pin = str(geo.get("postal_pin", ""))
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
            raw_address=request.raw_address,
            city=geo.get("city"),
            state=geo.get("state"),
            postal_pin=request.postal_pin if pin_matches else expected_pin,
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
                Evidence(key="reverse_geocode", value=geo, source="amazon_location"),
                Evidence(
                    key="coordinates",
                    value=request.coordinates.model_dump(),
                    source="browser_geolocation",
                ),
                Evidence(key="digipin", value=digipin, source="india_post_reference_algorithm"),
            ],
            actions=actions,
            data={
                "normalized_address": geo.get("label"),
                "digipin": digipin,
                "postal_pin": expected_pin,
                "address_id": address_id,
            },
            user_message={"en": summary, "hi": "Location se address aur DIGIPIN verify ho gaya."},
        )
