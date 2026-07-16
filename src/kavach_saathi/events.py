from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import redis

from kavach_saathi.redis_client import get_redis

if TYPE_CHECKING:
    from kavach_saathi.container import Container

logger = logging.getLogger(__name__)

REVIEW_SUBMITTED_STREAM = "events:review.submitted"
ORDER_PLACED_STREAM = "events:order.placed"


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
        return client.xadd(stream, {"data": json.dumps(payload)})
    except Exception:
        logger.exception("Failed to publish event to stream %s", stream)
        return None


def _ensure_group(client: redis.Redis, stream: str, group: str) -> None:
    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


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
    client = get_redis()
    try:
        _ensure_group(client, stream, group)
    except Exception:
        logger.exception("Could not initialize Redis consumer group %s; event consumer not started", group)
        return

    while stop_event is None or not stop_event.is_set():
        # Check this consumer's own still-pending entries first (id="0", non-blocking)
        # before waiting on new ones (id=">"). Without this, a message that failed or
        # stalled mid-processing (e.g. a slow first-time model download) would sit
        # unacked forever -- XREADGROUP with ">" only ever delivers messages that were
        # never handed to this consumer, it does not retry its own pending list.
        for read_id, block_ms in (("0", None), (">", 2000)):
            try:
                response = client.xreadgroup(group, consumer_name, {stream: read_id}, count=1, block=block_ms)
            except Exception:
                logger.exception("Redis stream read failed; retrying")
                time.sleep(2)
                continue
            if not response:
                continue
            for _stream_name, messages in response:
                for message_id, fields in messages:
                    try:
                        payload = json.loads(fields["data"])
                        asyncio.run(handler(payload))
                    except Exception:
                        logger.exception("Failed to process %s event %s", stream, message_id)
                    finally:
                        client.xack(stream, group, message_id)


async def _trigger_review_workflow(container: Container, payload: dict[str, Any]) -> None:
    from kavach_saathi.models import WorkflowType

    await container.service.execute(WorkflowType.REVIEW, payload)


async def _trigger_delivery_confirmation_call(container: Container, payload: dict[str, Any]) -> None:
    from kavach_saathi.config import get_settings
    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Address, Order
    from kavach_saathi.providers.twilio_integration import TwilioIntegrationClient

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
        except Exception:
            pass


def start_review_consumer(container: Container) -> threading.Thread:
    """Automatically invokes Agent 4 (ReviewFilterAgent) on every `review.submitted`
    event -- the real trigger path replacing the old manual "Check review truth"
    button (gap_report B4/Y2's event-driven requirement)."""

    async def handler(payload: dict[str, Any]) -> None:
        await _trigger_review_workflow(container, payload)

    thread = threading.Thread(
        target=_consume_stream,
        args=(REVIEW_SUBMITTED_STREAM, "agent4_review_filter", "worker-1", handler),
        daemon=True,
        name="review-event-consumer",
    )
    thread.start()
    return thread


def start_order_consumer(container: Container) -> threading.Thread:
    """Send the approved WhatsApp ownership template for each persisted order event."""

    async def handler(payload: dict[str, Any]) -> None:
        await _trigger_delivery_confirmation_call(container, payload)

    thread = threading.Thread(
        target=_consume_stream,
        args=(ORDER_PLACED_STREAM, "agent7_delivery_confirmation", "worker-1", handler),
        daemon=True,
        name="order-event-consumer",
    )
    thread.start()
    return thread
