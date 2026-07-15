from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from kavach_saathi.container import get_container


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Step Functions worker entrypoint for media-heavy workflows."""

    service = get_container().service
    record = asyncio.run(
        service.resume(
            UUID(event["run_id"]),
            order_id=event.get("order_id"),
        )
    )
    return record.model_dump(mode="json")
