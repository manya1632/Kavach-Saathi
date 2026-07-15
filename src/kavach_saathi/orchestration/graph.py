from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from kavach_saathi.agents import (
    AddressGuardianAgent,
    CatalogueTruthAgent,
    DeliveryConfirmationAgent,
    ReturnVerifierAgent,
    ReviewFilterAgent,
    SizeTranslatorAgent,
    SpecEnforcerAgent,
    VoiceQAAgent,
)
from kavach_saathi.models import (
    AddressVerifyRequest,
    AgentName,
    AgentResult,
    ConfirmationRequest,
    ListingAnalyzeRequest,
    ReturnAnalyzeRequest,
    ReviewAnalyzeRequest,
    SizeRecommendRequest,
    VoiceQueryRequest,
)


def merge_results(left: dict[str, AgentResult], right: dict[str, AgentResult]) -> dict[str, AgentResult]:
    return {**left, **right}


class WorkflowState(TypedDict, total=False):
    request: dict[str, Any]
    order_id: str
    results: Annotated[dict[str, AgentResult], merge_results]
    events: Annotated[list[dict[str, Any]], operator.add]
    intent: str


def event(agent: AgentName, message: str, phase: str = "completed") -> dict[str, Any]:
    return {"type": f"agent_{phase}", "agent": agent.value, "message": message}


class AgentGraphs:
    def __init__(
        self,
        *,
        catalogue: CatalogueTruthAgent,
        specs: SpecEnforcerAgent,
        size: SizeTranslatorAgent,
        review: ReviewFilterAgent,
        voice: VoiceQAAgent,
        address: AddressGuardianAgent,
        confirmation: DeliveryConfirmationAgent,
        returns: ReturnVerifierAgent,
    ):
        self.catalogue = catalogue
        self.specs = specs
        self.size = size
        self.review = review
        self.voice = voice
        self.address = address
        self.confirmation = confirmation
        self.returns = returns

        self.listing = self._listing_graph()
        self.size_workflow = self._single_graph("size", self._size_node)
        self.review_workflow = self._single_graph("review", self._review_node)
        self.voice_workflow = self._voice_graph()
        self.address_workflow = self._single_graph("address", self._address_node)
        self.confirmation_workflow = self._confirmation_graph()
        self.return_workflow = self._single_graph("return", self._return_node)

    async def _catalogue_node(self, state: WorkflowState) -> dict[str, Any]:
        result = await self.catalogue.run(ListingAnalyzeRequest.model_validate(state["request"]))
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _spec_node(self, state: WorkflowState) -> dict[str, Any]:
        result = await self.specs.run(ListingAnalyzeRequest.model_validate(state["request"]))
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _size_node(self, state: WorkflowState) -> dict[str, Any]:
        raw = state["request"]
        request = SizeRecommendRequest(
            buyer_id=raw["buyer_id"],
            product_id=raw["product_id"],
            idempotency_key=raw.get("idempotency_key"),
        )
        result = await self.size.run(request)
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _review_node(self, state: WorkflowState) -> dict[str, Any]:
        result = await self.review.run(ReviewAnalyzeRequest.model_validate(state["request"]))
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _voice_node(self, state: WorkflowState) -> dict[str, Any]:
        size_result = state.get("results", {}).get(AgentName.SIZE_TRANSLATOR.value)
        result = await self.voice.run(VoiceQueryRequest.model_validate(state["request"]), size_result=size_result)
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _address_node(self, state: WorkflowState) -> dict[str, Any]:
        raw = state["request"]
        if "updated_address" in raw and raw.get("updated_address"):
            raw = raw["updated_address"]
        result = await self.address.run(AddressVerifyRequest.model_validate(raw))
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _confirmation_node(self, state: WorkflowState) -> dict[str, Any]:
        result = await self.confirmation.run(state["order_id"], ConfirmationRequest.model_validate(state["request"]))
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _return_node(self, state: WorkflowState) -> dict[str, Any]:
        result = await self.returns.run(ReturnAnalyzeRequest.model_validate(state["request"]))
        return {
            "results": {result.agent.value: result},
            "events": [event(result.agent, result.summary)],
        }

    async def _finalize_listing(self, state: WorkflowState) -> dict[str, Any]:
        blocked = [
            result.agent.value
            for result in state["results"].values()
            if result.status.value in {"needs_evidence", "manual_review", "failed"}
        ]
        message = f"Listing held by: {', '.join(blocked)}" if blocked else "Listing evidence checks complete"
        return {"events": [{"type": "workflow_join", "message": message}]}

    def _listing_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("catalogue_truth", self._catalogue_node)
        graph.add_node("spec_enforcer", self._spec_node)
        graph.add_node("join", self._finalize_listing)
        graph.add_edge(START, "catalogue_truth")
        graph.add_edge(START, "spec_enforcer")
        graph.add_edge(["catalogue_truth", "spec_enforcer"], "join")
        graph.add_edge("join", END)
        return graph.compile()

    @staticmethod
    def _voice_intent(state: WorkflowState) -> dict[str, Any]:
        query = str(state["request"].get("text", "")).lower()
        is_comparison = bool(state["request"].get("compare_product_ids")) or any(
            word in query for word in ("compare", "comparison", "versus", " vs ", "bada", "chhota", "better", "sab ", "all ")
        )
        is_size = not is_comparison and any(word in query for word in ("size", "fit", "kaunsa", "konsa"))
        return {
            "intent": "size" if is_size else "general",
            "events": [
                {
                    "type": "supervisor_route",
                    "message": "Size workflow" if is_size else "Grounded Q&A workflow",
                }
            ],
        }

    def _voice_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("classify", self._voice_intent)
        graph.add_node("size_translator", self._size_node)
        graph.add_node("voice_qa", self._voice_node)
        graph.add_edge(START, "classify")
        graph.add_conditional_edges(
            "classify",
            lambda state: state["intent"],
            {"size": "size_translator", "general": "voice_qa"},
        )
        graph.add_edge("size_translator", "voice_qa")
        graph.add_edge("voice_qa", END)
        return graph.compile()

    @staticmethod
    def _confirmation_route(state: WorkflowState) -> str:
        return "address" if state["request"].get("decision") == "update_address" else "done"

    def _confirmation_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("delivery_confirmation", self._confirmation_node)
        graph.add_node("address_guardian", self._address_node)
        graph.add_edge(START, "delivery_confirmation")
        graph.add_conditional_edges(
            "delivery_confirmation",
            self._confirmation_route,
            {"address": "address_guardian", "done": END},
        )
        graph.add_edge("address_guardian", END)
        return graph.compile()

    @staticmethod
    def _single_graph(name: str, node):
        graph = StateGraph(WorkflowState)
        graph.add_node(name, node)
        graph.add_edge(START, name)
        graph.add_edge(name, END)
        return graph.compile()
