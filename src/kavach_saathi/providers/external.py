from __future__ import annotations

import base64
import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from kavach_saathi.config import Settings


class ExternalProvider(ABC):
    @abstractmethod
    async def reverse_image_search(
        self, image_key: str, ground_truth: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def transcribe(self, audio_key: str, language: str, ground_truth: str | None = None) -> str: ...

    @abstractmethod
    async def synthesize(self, text: str, language: str) -> str: ...

    @abstractmethod
    async def reverse_geocode(self, latitude: float, longitude: float) -> dict[str, Any]: ...


class DemoExternalProvider(ExternalProvider):
    async def reverse_image_search(self, image_key: str, ground_truth: dict[str, Any] | None = None) -> dict[str, Any]:
        return ground_truth or {"full_matches": [], "partial_matches": [], "pages": []}

    async def transcribe(self, audio_key: str, language: str, ground_truth: str | None = None) -> str:
        return ground_truth or "Mujhe kaunsa size lena chahiye?"

    async def synthesize(self, text: str, language: str) -> str:
        return f"assets/mock/audio/demo-{language}.wav"

    async def reverse_geocode(self, latitude: float, longitude: float) -> dict[str, Any]:
        places = [
            (22.0797, 82.1409, "Bilaspur", "Chhattisgarh", "495001"),
            (25.5941, 85.1376, "Patna", "Bihar", "800001"),
            (26.9124, 75.7873, "Jaipur", "Rajasthan", "302001"),
            (26.8467, 80.9462, "Lucknow", "Uttar Pradesh", "226001"),
        ]
        _, _, city, state, pin = min(
            places,
            key=lambda item: abs(item[0] - latitude) + abs(item[1] - longitude),
        )
        locality = "Lingiadih" if city == "Bilaspur" else ""
        return {
            "label": f"Verified landmark address, {city}, {state} {pin}",
            "locality": locality,
            "city": city,
            "state": state,
            "postal_pin": pin,
        }


class LiveExternalProvider(ExternalProvider):
    def __init__(self, settings: Settings):
        import boto3

        self.settings = settings
        self.location = boto3.client("geo-places", region_name=settings.aws_region)

    async def reverse_image_search(self, image_key: str, ground_truth: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            from google.cloud import vision
        except ImportError as exc:
            raise RuntimeError("google-cloud-vision is required for live web detection") from exc

        credentials = None
        if self.settings.google_service_account_json:
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_info(
                json.loads(self.settings.google_service_account_json)
            )
        client = vision.ImageAnnotatorClient(credentials=credentials)
        image = vision.Image()
        if image_key.startswith("http") or image_key.startswith("gs://"):
            image.source.image_uri = image_key
        else:
            import boto3

            body = (
                boto3.client("s3", region_name=self.settings.aws_region)
                .get_object(Bucket=self.settings.media_bucket, Key=image_key)["Body"]
                .read()
            )
            image.content = body
        result = client.web_detection(image=image).web_detection
        return {
            "full_matches": [item.url for item in result.full_matching_images],
            "partial_matches": [item.url for item in result.partial_matching_images],
            "pages": [item.url for item in result.pages_with_matching_images],
        }

    async def _bhashini_config(self, task_type: str, language: str) -> dict[str, Any]:
        if not all(
            [
                self.settings.bhashini_user_id,
                self.settings.bhashini_api_key,
                self.settings.bhashini_pipeline_id,
            ]
        ):
            raise RuntimeError("Bhashini credentials and pipeline ID are required")
        payload = {
            "pipelineTasks": [{"taskType": task_type, "config": {"language": {"sourceLanguage": language}}}],
            "pipelineRequestConfig": {"pipelineId": self.settings.bhashini_pipeline_id},
        }
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.post(
                self.settings.bhashini_config_url,
                headers={
                    "userID": self.settings.bhashini_user_id,
                    "ulcaApiKey": self.settings.bhashini_api_key,
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def _bhashini_compute(self, task_type: str, language: str, data: dict[str, Any]) -> dict[str, Any]:
        config = await self._bhashini_config(task_type, language)
        endpoint = config.get("pipelineInferenceAPIEndPoint") or config.get("pipelineInferenceAPIEnfPoint")
        if not endpoint:
            raise RuntimeError("Bhashini configuration did not include an inference endpoint")
        callback = endpoint.get("callbackUrl") or endpoint.get("callbackURL")
        if not callback:
            raise RuntimeError("Bhashini configuration did not include a callback URL")
        auth = endpoint["inferenceApiKey"]
        service = config["pipelineResponseConfig"][0]["config"][0]["serviceId"]
        payload = {
            "pipelineTasks": [
                {
                    "taskType": task_type,
                    "config": {"language": {"sourceLanguage": language}, "serviceId": service},
                }
            ],
            "inputData": data,
        }
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.post(callback, headers={auth["name"]: auth["value"]}, json=payload)
            response.raise_for_status()
            return response.json()

    async def transcribe(self, audio_key: str, language: str, ground_truth: str | None = None) -> str:
        import boto3

        audio = (
            boto3.client("s3", region_name=self.settings.aws_region)
            .get_object(Bucket=self.settings.media_bucket, Key=audio_key)["Body"]
            .read()
        )
        response = await self._bhashini_compute(
            "asr", language, {"audio": [{"audioContent": base64.b64encode(audio).decode()}]}
        )
        return response["pipelineResponse"][0]["output"][0]["source"]

    async def synthesize(self, text: str, language: str) -> str:
        response = await self._bhashini_compute("tts", language, {"input": [{"source": text}]})
        audio = base64.b64decode(response["pipelineResponse"][0]["audio"][0]["audioContent"])
        key = f"generated/audio/{hashlib.sha1(text.encode()).hexdigest()[:16]}.wav"
        import boto3

        boto3.client("s3", region_name=self.settings.aws_region).put_object(
            Bucket=self.settings.media_bucket, Key=key, Body=audio, ContentType="audio/wav"
        )
        return key

    async def reverse_geocode(self, latitude: float, longitude: float) -> dict[str, Any]:
        response = self.location.reverse_geocode(QueryPosition=[longitude, latitude], MaxResults=1)
        place = response["ResultItems"][0]
        address = place["Address"]
        return {
            "label": address.get("Label", ""),
            "locality": address.get("Neighborhood", "") or address.get("Sublocality", "") or "",
            "city": address.get("Locality", ""),
            "state": address.get("Region", {}).get("Name", ""),
            "postal_pin": address.get("PostalCode", ""),
        }
