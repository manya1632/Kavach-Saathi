from __future__ import annotations

import json
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import UUID

from sqlalchemy import select

from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import WorkflowRun
from kavach_saathi.models import RunRecord, RunStatus


class WorkflowStore(ABC):
    @abstractmethod
    def create(self, record: RunRecord, idempotency_key: str | None = None) -> RunRecord: ...

    @abstractmethod
    def get(self, run_id: UUID) -> RunRecord | None: ...

    @abstractmethod
    def save(self, record: RunRecord) -> RunRecord: ...

    @abstractmethod
    def find_idempotent(self, key: str) -> RunRecord | None: ...


class MemoryWorkflowStore(WorkflowStore):
    def __init__(self) -> None:
        self._records: dict[UUID, RunRecord] = {}
        self._idempotency: dict[str, UUID] = {}
        self._lock = RLock()

    def create(self, record: RunRecord, idempotency_key: str | None = None) -> RunRecord:
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency:
                return deepcopy(self._records[self._idempotency[idempotency_key]])
            self._records[record.run_id] = deepcopy(record)
            if idempotency_key:
                self._idempotency[idempotency_key] = record.run_id
            return deepcopy(record)

    def get(self, run_id: UUID) -> RunRecord | None:
        with self._lock:
            record = self._records.get(run_id)
            return deepcopy(record) if record else None

    def save(self, record: RunRecord) -> RunRecord:
        with self._lock:
            record.updated_at = datetime.now(UTC)
            self._records[record.run_id] = deepcopy(record)
            return deepcopy(record)

    def find_idempotent(self, key: str) -> RunRecord | None:
        with self._lock:
            run_id = self._idempotency.get(key)
            return deepcopy(self._records[run_id]) if run_id else None


class PostgresWorkflowStore(WorkflowStore):
    """Persists queued, running, completed, and failed agent runs across restarts."""

    @staticmethod
    def _payload(record: RunRecord) -> dict[str, Any]:
        return json.loads(record.model_dump_json())

    def create(self, record: RunRecord, idempotency_key: str | None = None) -> RunRecord:
        if idempotency_key:
            existing = self.find_idempotent(idempotency_key)
            if existing:
                return existing
        with SessionLocal() as session:
            session.add(
                WorkflowRun(
                    run_id=str(record.run_id),
                    idempotency_key=idempotency_key,
                    payload=self._payload(record),
                )
            )
            session.commit()
        return record

    def get(self, run_id: UUID) -> RunRecord | None:
        with SessionLocal() as session:
            row = session.get(WorkflowRun, str(run_id))
            return RunRecord.model_validate(row.payload) if row else None

    def save(self, record: RunRecord) -> RunRecord:
        record.updated_at = datetime.now(UTC)
        with SessionLocal() as session:
            row = session.get(WorkflowRun, str(record.run_id))
            if row:
                row.payload = self._payload(record)
            else:
                session.add(WorkflowRun(run_id=str(record.run_id), payload=self._payload(record)))
            session.commit()
        return record

    def find_idempotent(self, key: str) -> RunRecord | None:
        with SessionLocal() as session:
            row = session.execute(
                select(WorkflowRun).where(WorkflowRun.idempotency_key == key)
            ).scalars().first()
            return RunRecord.model_validate(row.payload) if row else None


class DynamoDBWorkflowStore(WorkflowStore):
    """DynamoDB adapter used in deployed mode.

    The table uses `run_id` as its partition key and a GSI named
    `idempotency-key-index` when idempotent lookup is required.
    """

    def __init__(self, table_name: str, region: str):
        import boto3

        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    @staticmethod
    def _item(record: RunRecord, idempotency_key: str | None = None) -> dict[str, Any]:
        payload = json.loads(record.model_dump_json())
        payload["run_id"] = str(record.run_id)
        payload["trace_id"] = str(record.trace_id)
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return payload

    def create(self, record: RunRecord, idempotency_key: str | None = None) -> RunRecord:
        if idempotency_key:
            existing = self.find_idempotent(idempotency_key)
            if existing:
                return existing
        self.table.put_item(
            Item=self._item(record, idempotency_key),
            ConditionExpression="attribute_not_exists(run_id)",
        )
        return record

    def get(self, run_id: UUID) -> RunRecord | None:
        response = self.table.get_item(Key={"run_id": str(run_id)}, ConsistentRead=True)
        item = response.get("Item")
        return RunRecord.model_validate(item) if item else None

    def save(self, record: RunRecord) -> RunRecord:
        record.updated_at = datetime.now(UTC)
        previous = self.table.get_item(Key={"run_id": str(record.run_id)}).get("Item", {})
        self.table.put_item(Item=self._item(record, previous.get("idempotency_key")))
        return record

    def find_idempotent(self, key: str) -> RunRecord | None:
        from boto3.dynamodb.conditions import Key

        response = self.table.query(
            IndexName="idempotency-key-index",
            KeyConditionExpression=Key("idempotency_key").eq(key),
            Limit=1,
        )
        items = response.get("Items", [])
        return RunRecord.model_validate(items[0]) if items else None


def status_from_results(statuses: list[RunStatus]) -> RunStatus:
    if any(status == RunStatus.FAILED for status in statuses):
        return RunStatus.FAILED
    if any(status == RunStatus.RETRYABLE for status in statuses):
        return RunStatus.RETRYABLE
    if any(status == RunStatus.MANUAL_REVIEW for status in statuses):
        return RunStatus.MANUAL_REVIEW
    if any(status == RunStatus.NEEDS_EVIDENCE for status in statuses):
        return RunStatus.NEEDS_EVIDENCE
    return RunStatus.COMPLETED
