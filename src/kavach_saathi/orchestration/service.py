from __future__ import annotations

from typing import Any
from uuid import UUID

from kavach_saathi.models import (
    RunEnvelope,
    RunEvent,
    RunRecord,
    RunStatus,
    WorkflowType,
)
from kavach_saathi.orchestration.graph import AgentGraphs
from kavach_saathi.store import WorkflowStore, status_from_results


class RunNotFoundError(KeyError):
    pass


class OrchestrationService:
    def __init__(self, graphs: AgentGraphs, store: WorkflowStore):
        self.graphs = graphs
        self.store = store

    def _graph(self, workflow: WorkflowType):
        return {
            WorkflowType.LISTING: self.graphs.listing,
            WorkflowType.SIZE: self.graphs.size_workflow,
            WorkflowType.REVIEW: self.graphs.review_workflow,
            WorkflowType.REVIEW_SUMMARY: self.graphs.review_summary_workflow,
            WorkflowType.VOICE: self.graphs.voice_workflow,
            WorkflowType.ADDRESS: self.graphs.address_workflow,
            WorkflowType.RETURN: self.graphs.return_workflow,
        }[workflow]

    def start(
        self,
        workflow: WorkflowType,
        request: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        if idempotency_key:
            existing = self.store.find_idempotent(idempotency_key)
            if existing:
                return existing

        record = RunRecord(workflow=workflow, request=request, status=RunStatus.QUEUED)
        record.events.append(
            RunEvent(
                sequence=1,
                type="workflow_started",
                message=f"Supervisor accepted {workflow.value} workflow",
            )
        )
        return self.store.create(record, idempotency_key)

    async def resume(self, run_id: UUID, *, order_id: str | None = None) -> RunRecord:
        record = self.get(run_id)
        if record.status not in {RunStatus.QUEUED, RunStatus.RETRYABLE, RunStatus.RUNNING}:
            return record
        record.status = RunStatus.RUNNING
        self.store.save(record)

        try:
            state = await self._graph(record.workflow).ainvoke(
                {
                    "request": record.request,
                    "order_id": order_id or "",
                    "results": {},
                    "events": [],
                }
            )
            record.results = state.get("results", {})
            for item in state.get("events", []):
                record.events.append(
                    RunEvent(
                        sequence=len(record.events) + 1,
                        type=item["type"],
                        agent=item.get("agent"),
                        message=item["message"],
                        data=item.get("data", {}),
                    )
                )
            record.status = status_from_results([result.status for result in record.results.values()])
            record.events.append(
                RunEvent(
                    sequence=len(record.events) + 1,
                    type="workflow_completed",
                    message=f"Workflow finished with status {record.status.value}",
                )
            )
        except Exception as exc:
            record.status = RunStatus.FAILED
            record.error = str(exc)
            record.events.append(
                RunEvent(
                    sequence=len(record.events) + 1,
                    type="workflow_failed",
                    message=str(exc),
                )
            )
        return self.store.save(record)

    async def execute(
        self,
        workflow: WorkflowType,
        request: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        order_id: str | None = None,
    ) -> RunRecord:
        record = self.start(workflow, request, idempotency_key=idempotency_key)
        if record.status != RunStatus.QUEUED:
            return record
        return await self.resume(record.run_id, order_id=order_id)

    def get(self, run_id: UUID) -> RunRecord:
        record = self.store.get(run_id)
        if not record:
            raise RunNotFoundError(str(run_id))
        return record

    @staticmethod
    def envelope(record: RunRecord) -> RunEnvelope:
        return RunEnvelope(
            run_id=record.run_id,
            trace_id=record.trace_id,
            workflow=record.workflow,
            status=record.status,
            results=record.results,
            error=record.error,
        )
