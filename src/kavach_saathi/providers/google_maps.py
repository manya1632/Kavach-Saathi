from __future__ import annotations

from typing import Any

import httpx

from kavach_saathi.config import Settings

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Indian-language script ranges (Devanagari, Bengali, Gujarati, Gurmukhi, Tamil,
# Telugu, Kannada, Malayalam, Odia) -- if a buyer-entered address contains any of
# these, it needs Indic normalization before Google's geocoder sees it.
_INDIC_SCRIPT_RANGES = (
    (0x0900, 0x097F),  # Devanagari
    (0x0980, 0x09FF),  # Bengali
    (0x0A00, 0x0A7F),  # Gurmukhi
    (0x0A80, 0x0AFF),  # Gujarati
    (0x0B00, 0x0B7F),  # Odia
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0C80, 0x0CFF),  # Kannada
    (0x0D00, 0x0D7F),  # Malayalam
)

_LANG_BY_RANGE = {
    (0x0900, 0x097F): "hi",
    (0x0980, 0x09FF): "bn",
    (0x0A00, 0x0A7F): "pa",
    (0x0A80, 0x0AFF): "gu",
    (0x0B00, 0x0B7F): "or",
    (0x0B80, 0x0BFF): "ta",
    (0x0C00, 0x0C7F): "te",
    (0x0C80, 0x0CFF): "kn",
    (0x0D00, 0x0D7F): "ml",
}


def _detect_indic_language(text: str) -> str | None:
    for char in text:
        codepoint = ord(char)
        for low, high in _INDIC_SCRIPT_RANGES:
            if low <= codepoint <= high:
                return _LANG_BY_RANGE[(low, high)]
    return None


def normalize_indic_address(raw_address: str) -> str:
    """Real IndicNLP normalization (final target plan.md Agent 6: "Google Maps
    Geocoding + IndicNLP parsing") -- Indian buyers who type addresses in Devanagari
    or another Indic script often get inconsistent Unicode encoding of the same
    visual character (e.g. multiple ways to encode a matra), which can trip up a
    geocoder. Runs IndicNLP's real normalizer when Indic script is detected; passes
    Latin-script/Hinglish text through unchanged.
    """
    language = _detect_indic_language(raw_address)
    if not language:
        return raw_address
    from indicnlp.normalize.indic_normalize import IndicNormalizerFactory

    normalizer = IndicNormalizerFactory().get_normalizer(language)
    return normalizer.normalize(raw_address)


class GoogleMapsUnavailable(RuntimeError):
    pass


class GoogleMapsGeocoder:
    """Real Google Maps Geocoding API client (final target plan.md Agent 6 -- the
    plan's own stack table names Amazon Location; Google Maps Geocoding is the
    provider actually configured for this project, see project notes). Config-gated
    on GOOGLE_MAPS_API_KEY; callers must catch GoogleMapsUnavailable and degrade
    honestly rather than fake a resolved address.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.google_maps_api_key)

    async def reverse_geocode(self, latitude: float, longitude: float) -> dict[str, Any]:
        if not self.is_configured:
            raise GoogleMapsUnavailable("GOOGLE_MAPS_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.get(
                _GEOCODE_URL,
                params={"latlng": f"{latitude},{longitude}", "key": self.settings.google_maps_api_key},
            )
            response.raise_for_status()
            payload = response.json()

        if payload.get("status") != "OK" or not payload.get("results"):
            raise GoogleMapsUnavailable(f"Google Maps returned status={payload.get('status')}")

        result = payload["results"][0]
        components = {
            component_type: component["long_name"]
            for component in result.get("address_components", [])
            for component_type in component.get("types", [])
        }
        return {
            "label": result.get("formatted_address", ""),
            "locality": components.get("sublocality") or components.get("sublocality_level_1") or components.get("neighborhood") or "",
            "city": components.get("locality") or components.get("administrative_area_level_2", ""),
            "district": components.get("administrative_area_level_2", ""),
            "state": components.get("administrative_area_level_1", ""),
            "postal_pin": components.get("postal_code", ""),
        }

    async def geocode(self, address: str) -> dict[str, Any]:
        if not self.is_configured:
            raise GoogleMapsUnavailable("GOOGLE_MAPS_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.get(
                _GEOCODE_URL,
                params={"address": address, "key": self.settings.google_maps_api_key},
            )
            response.raise_for_status()
            payload = response.json()

        if payload.get("status") != "OK" or not payload.get("results"):
            raise GoogleMapsUnavailable(f"Google Maps returned status={payload.get('status')}")

        result = payload["results"][0]
        location = result.get("geometry", {}).get("location", {})
        components = {
            component_type: component["long_name"]
            for component in result.get("address_components", [])
            for component_type in component.get("types", [])
        }
        return {
            "label": result.get("formatted_address", ""),
            "locality": components.get("sublocality") or components.get("sublocality_level_1") or components.get("neighborhood") or "",
            "city": components.get("locality") or components.get("administrative_area_level_2", ""),
            "district": components.get("administrative_area_level_2", ""),
            "state": components.get("administrative_area_level_1", ""),
            "postal_pin": components.get("postal_code", ""),
            "latitude": location.get("lat", 0.0),
            "longitude": location.get("lng", 0.0),
        }
