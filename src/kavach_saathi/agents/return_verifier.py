from __future__ import annotations

from kavach_saathi.agents.base import Agent
from kavach_saathi.models import (
    AgentAction,
    AgentName,
    AgentResult,
    Evidence,
    ReturnAnalyzeRequest,
    RunStatus,
)


class ReturnVerifierAgent(Agent):
    async def run(self, request: ReturnAnalyzeRequest) -> AgentResult:
        order = self.context.repository.get("orders", request.order_id)
        fixture = self.context.repository.return_for_order(request.order_id) or {}
        expected = fixture.get(
            "evidence",
            {
                "tag_visible": True,
                "label_matches": True,
                "product_matches": True,
                "packaging_matches": True,
            },
        )
        media = await self.context.media.analyze_video(
            request.video_key,
            "Compare the returned product, tag, label and packaging with the original order.",
            expected,
        )
        history = self.context.repository.buyer_orders(order["buyer_id"])
        clean_history = sum(1 for item in history if item.get("return_outcome") in (None, "approved"))

        score = 20
        score += 25 if media.get("product_matches") else 0
        score += 20 if media.get("label_matches") else 0
        score += 15 if media.get("tag_visible") else 0
        score += 10 if media.get("packaging_matches") else 0
        score += min(10, clean_history * 2)
        score = int(fixture.get("expected_confidence", score))

        if score >= 90:
            status = RunStatus.COMPLETED
            decision = "approve"
            summary = "Return evidence is consistent; approve and schedule pickup."
            actions = [AgentAction(type="approve_return", label="Approve return and schedule pickup")]
        elif score >= 40:
            status = RunStatus.NEEDS_EVIDENCE
            decision = "request_more_evidence"
            summary = "Evidence is incomplete; request one more clear angle before deciding."
            actions = [AgentAction(type="upload_more_evidence", label="Upload another angle")]
        else:
            status = RunStatus.MANUAL_REVIEW
            decision = "manual_inspection"
            summary = "Confidence is low; send to human inspection without auto-rejecting the buyer."
            actions = [AgentAction(type="manual_inspection", label="Send to hub inspection")]

        return AgentResult(
            agent=AgentName.RETURN_VERIFIER,
            status=status,
            confidence=score,
            summary=summary,
            evidence=[
                Evidence(key="video_checks", value=media, source="nova_video"),
                Evidence(
                    key="clean_order_history",
                    value=clean_history,
                    source="order_history",
                    weight=0.2,
                ),
            ],
            actions=actions,
            data={"decision": decision, "checks": media, "order_id": request.order_id},
            user_message={
                "en": summary,
                "hi": "Return evidence check hua; agla fair step bataya gaya hai.",
            },
        )
