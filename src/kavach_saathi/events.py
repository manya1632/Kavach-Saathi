from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

import redis

from kavach_saathi.redis_client import get_redis, get_stream_redis

if TYPE_CHECKING:
    from kavach_saathi.container import Container

logger = logging.getLogger(__name__)

REVIEW_SUBMITTED_STREAM = "events:review.submitted"
ORDER_PLACED_STREAM = "events:order.placed"
WORKFLOW_QUEUED_STREAM = "events:workflow.queued"


def publish_event(stream: str, payload: dict[str, Any]) -> str | None:
    """Real Redis Streams XADD -- the plan's event bus (Section 8: "AWS SQS/SNS, or
    Kafka if self-hosting"; Redis Streams is the self-hosted substitute, see project
    notes). Returns the stream entry ID, or None if Redis is unreachable. The caller
    must have already durably persisted whatever the event describes (the order/review
    row itself), so a missed publish degrades to "no automatic agent trigger" rather
    than losing the underlying write.
    """
    try:
        client = get_redis()
        # Approximate trimming is O(1) and prevents an indefinitely growing stream
        # while retaining ample replay history for consumer recovery.
        return client.xadd(stream, {"data": json.dumps(payload)}, maxlen=10_000, approximate=True)
    except Exception:
        logger.exception("Failed to publish event to stream %s", stream)
        return None


def _ensure_group(client: redis.Redis, stream: str, group: str) -> None:
    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _restore_missing_group(client: redis.Redis, stream: str, group: str, exc: Exception) -> bool:
    """Recreate a group if Redis was flushed or the stream expired mid-loop."""
    if not isinstance(exc, redis.ResponseError) or "NOGROUP" not in str(exc):
        return False
    _ensure_group(client, stream, group)
    logger.warning("Recreated missing Redis consumer group %s for %s", group, stream)
    return True


def _consume_stream(
    stream: str,
    group: str,
    consumer_name: str,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    stop_event: threading.Event | None = None,
) -> None:
    """Blocking consumer-group loop shared by every stream consumer -- run on a
    dedicated background thread from app startup. Real XREADGROUP/XACK semantics
    (redelivery on crash, multiple workers could scale out later), not a polling
    shortcut.
    """
    client = get_stream_redis()
    try:
        _ensure_group(client, stream, group)
    except Exception:
        logger.exception("Could not initialize Redis consumer group %s; event consumer not started", group)
        return

    while stop_event is None or not stop_event.is_set():
        # Recover entries left pending by a crashed/restarted instance. Unique
        # consumer names avoid multiple replicas pretending to be the same worker;
        # XAUTOCLAIM transfers only entries idle for at least one minute.
        try:
            claimed = client.xautoclaim(
                stream,
                group,
                consumer_name,
                min_idle_time=60_000,
                start_id="0-0",
                count=10,
            )
            for message_id, fields in claimed[1]:
                _process_message(client, stream, group, message_id, fields, handler)
        except Exception as exc:
            if _restore_missing_group(client, stream, group, exc):
                continue
            logger.exception("Redis pending-event recovery failed; continuing with owned/new events")

        # Check this consumer's own still-pending entries first (id="0", non-blocking)
        # before waiting on new ones (id=">"). Without this, a message that failed or
        # stalled mid-processing (e.g. a slow first-time model download) would sit
        # unacked forever -- XREADGROUP with ">" only ever delivers messages that were
        # never handed to this consumer, it does not retry its own pending list.
        for read_id, block_ms in (("0", None), (">", 2000)):
            try:
                response = client.xreadgroup(group, consumer_name, {stream: read_id}, count=1, block=block_ms)
            except Exception as exc:
                if _restore_missing_group(client, stream, group, exc):
                    break
                logger.exception("Redis stream read failed; retrying")
                time.sleep(2)
                continue
            if not response:
                continue
            for _stream_name, messages in response:
                for message_id, fields in messages:
                    _process_message(client, stream, group, message_id, fields, handler)


def _process_message(
    client: redis.Redis,
    stream: str,
    group: str,
    message_id: str,
    fields: dict[str, Any],
    handler: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    max_attempts: int = 3,
) -> None:
    """Acknowledge only success, or a durable move to the dead-letter stream."""
    attempt_key = f"event-attempt:{stream}:{group}:{message_id}"
    try:
        payload = json.loads(fields["data"])
        asyncio.run(handler(payload))
    except Exception as exc:
        logger.exception("Failed to process %s event %s", stream, message_id)
        attempts = int(client.incr(attempt_key))
        client.expire(attempt_key, 604_800)
        if attempts >= max_attempts:
            client.xadd(
                f"{stream}.dead-letter",
                {
                    "source_stream": stream,
                    "source_message_id": message_id,
                    "data": fields.get("data", "{}"),
                    "error_type": type(exc).__name__,
                },
                maxlen=1_000,
                approximate=True,
            )
            client.xack(stream, group, message_id)
            client.delete(attempt_key)
            return
        time.sleep(min(2**attempts, 10))
        return

    client.xack(stream, group, message_id)
    client.delete(attempt_key)


async def _trigger_review_workflow(container: Container, payload: dict[str, Any]) -> None:
    from kavach_saathi.models import WorkflowType

    await container.service.execute(WorkflowType.REVIEW, payload)


async def _trigger_delivery_confirmation_call(container: Container, payload: dict[str, Any]) -> None:
    from kavach_saathi.config import get_settings
    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Address, Order
    from kavach_saathi.providers.twilio_integration import TwilioIntegrationClient, normalize_phone_number

    with SessionLocal() as session:
        order = session.get(Order, payload["order_id"])
        if not order or order.whatsapp_workflow_state != "awaiting_order_confirmation":
            return
        address = session.get(Address, order.address_id)
        phone = (order.address_snapshot or {}).get("phone") or (address.phone if address else None)
        if not phone:
            raise RuntimeError("Order confirmation phone number is unavailable")
        settings = get_settings()
        sid = TwilioIntegrationClient(settings).send_whatsapp_content(
            phone,
            settings.twilio_order_confirmation_content_sid or "",
            {"1": order.id},
        )
        order.whatsapp_workflow_state = "ownership_prompt_sent"
        session.commit()
        try:
            get_redis().setex(f"whatsapp:outbound:{sid}", 86400, order.id)
            get_redis().setex(f"whatsapp:pending:{normalize_phone_number(phone)}", 86400, order.id)
        except Exception:
            pass


async def _trigger_workflow(container: Container, payload: dict[str, Any]) -> None:
    await container.service.resume(UUID(payload["run_id"]), order_id=payload.get("order_id"))


def enqueue_workflow(run_id: UUID, *, order_id: str | None = None) -> bool:
    return publish_event(
        WORKFLOW_QUEUED_STREAM,
        {"run_id": str(run_id), "order_id": order_id},
    ) is not None


def start_review_consumer(container: Container) -> threading.Thread:
    """Automatically invokes Agent 4 (ReviewFilterAgent) on every `review.submitted`
    event -- the real trigger path replacing the old manual "Check review truth"
    button (gap_report B4/Y2's event-driven requirement)."""

    async def handler(payload: dict[str, Any]) -> None:
        await _trigger_review_workflow(container, payload)

    consumer_name = f"worker-{socket.gethostname()}-{os.getpid()}-review"
    thread = threading.Thread(
        target=_consume_stream,
        args=(REVIEW_SUBMITTED_STREAM, "agent4_review_filter", consumer_name, handler),
        daemon=True,
        name="review-event-consumer",
    )
    thread.start()
    return thread


def start_order_consumer(container: Container) -> threading.Thread:
    """Send the approved WhatsApp ownership template for each persisted order event."""

    async def handler(payload: dict[str, Any]) -> None:
        await _trigger_delivery_confirmation_call(container, payload)

    consumer_name = f"worker-{socket.gethostname()}-{os.getpid()}-order"
    thread = threading.Thread(
        target=_consume_stream,
        args=(ORDER_PLACED_STREAM, "agent7_delivery_confirmation", consumer_name, handler),
        daemon=True,
        name="order-event-consumer",
    )
    thread.start()
    return thread


def start_workflow_consumer(container: Container) -> threading.Thread:
    """Resume queued model workflows outside the latency-sensitive API process."""

    async def handler(payload: dict[str, Any]) -> None:
        await _trigger_workflow(container, payload)

    consumer_name = f"worker-{socket.gethostname()}-{os.getpid()}-workflow"
    thread = threading.Thread(
        target=_consume_stream,
        args=(WORKFLOW_QUEUED_STREAM, "agent_workflows", consumer_name, handler),
        daemon=True,
        name="workflow-event-consumer",
    )
    thread.start()
    return thread
