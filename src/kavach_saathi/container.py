from __future__ import annotations

import json
from functools import lru_cache

from kavach_saathi.agents import (
    AddressGuardianAgent,
    CatalogueTruthAgent,
    DeliveryConfirmationAgent,
    ReturnVerifierAgent,
    ReviewFilterAgent,
    ReviewSummaryAgent,
    SizeTranslatorAgent,
    SpecEnforcerAgent,
    VoiceQAAgent,
)
from kavach_saathi.agents.base import AgentContext
from kavach_saathi.config import Settings, get_settings
from kavach_saathi.orchestration.graph import AgentGraphs
from kavach_saathi.orchestration.service import OrchestrationService
from kavach_saathi.providers.external import DemoExternalProvider, LiveExternalProvider
from kavach_saathi.providers.media import BedrockMediaProvider, DemoMediaProvider
from kavach_saathi.providers.reasoning import (
    CascadingReasoningProvider,
    DemoReasoningProvider,
    GeminiReasoningProvider,
    GroqReasoningProvider,
    ReasoningProvider,
)
from kavach_saathi.repository import CommerceRepository
from kavach_saathi.store import PostgresWorkflowStore


def _select_reasoner(settings: Settings) -> ReasoningProvider:
    """Gemini is the free-tier substitute for the plan's named Claude reasoning
    provider (Agents 2/3/5/7) -- see project notes. When both keys are configured,
    Groq runs as a real-time cascading fallback rather than a static either/or pick:
    live testing (Sub-phase 8) repeatedly hit Gemini's shared model capacity returning
    a transient 503 "high demand", and Groq's separate infrastructure makes it a
    genuine second attempt rather than hitting the same failure. Demo is the last
    resort when neither key is configured.
    """
    candidates: list[ReasoningProvider] = []
    if settings.gemini_api_key:
        candidates.append(GeminiReasoningProvider(settings))
    if settings.groq_api_key:
        candidates.append(GroqReasoningProvider(settings))
    if not candidates:
        return DemoReasoningProvider()
    if len(candidates) == 1:
        return candidates[0]
    return CascadingReasoningProvider(candidates)


class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Postgres is the single commerce data store for both demo and live mode now —
        # no more JSON-fixture vs DynamoDB storage split.
        self.repository = CommerceRepository()
        if settings.is_live:
            self._hydrate_external_secrets(settings)
            if not settings.groq_api_key and not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY or GROQ_API_KEY is missing from the configured secret")
            reasoner = _select_reasoner(settings)
            media = BedrockMediaProvider(settings)
            external = LiveExternalProvider(settings)
        else:
            reasoner = _select_reasoner(settings)
            media = DemoMediaProvider(settings)
            external = DemoExternalProvider()
        store = PostgresWorkflowStore()

        context = AgentContext(
            settings=settings,
            repository=self.repository,
            reasoner=reasoner,
            media=media,
            external=external,
        )
        self.address_agent = AddressGuardianAgent(context)
        graphs = AgentGraphs(
            catalogue=CatalogueTruthAgent(context),
            specs=SpecEnforcerAgent(context),
            size=SizeTranslatorAgent(context),
            review=ReviewFilterAgent(context),
            review_summary=ReviewSummaryAgent(context),
            voice=VoiceQAAgent(context),
            address=self.address_agent,
            confirmation=DeliveryConfirmationAgent(context),
            returns=ReturnVerifierAgent(context),
        )
        self.service = OrchestrationService(graphs, store)

    @staticmethod
    def _hydrate_external_secrets(settings: Settings) -> None:
        if not settings.external_secret_arn:
            return
        import boto3

        value = boto3.client("secretsmanager", region_name=settings.aws_region).get_secret_value(
            SecretId=settings.external_secret_arn
        )["SecretString"]
        payload = json.loads(value)
        for field in (
            "groq_api_key",
            "bhashini_user_id",
            "bhashini_api_key",
            "bhashini_pipeline_id",
            "google_application_credentials",
            "google_service_account_json",
            "twilio_account_sid",
            "twilio_auth_token",
            "twilio_from_number",
        ):
            if payload.get(field):
                setattr(settings, field, payload[field])


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
