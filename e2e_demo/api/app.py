from __future__ import annotations

import json

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from typing import Any

app = FastAPI()

# In-memory "DBs"
SOURCE_ITEMS: list[dict[str, Any]] = []
SINK_ITEMS_BY_EXTERNAL_ID: dict[str, dict[str, Any]] = {}
IDEMPOTENCY_RECORDS: dict[str, dict[str, Any]] = {}

# Failure simulation flags (deterministic)
FAIL_SOURCE_PAGE_2_ONCE = True
SINK_429_EVERY_N_CALLS = 5
_sink_write_calls = 0


class SinkUpsert(BaseModel):
    external_id: str
    name: str
    value: int


@app.on_event("startup")
def seed_source() -> None:
    # seed 25 items => with limit=10 you'll get 3 pages
    global SOURCE_ITEMS
    SOURCE_ITEMS = [
        {"external_id": f"item-{i}", "name": f"Item {i}", "value": i}
        for i in range(1, 26)
    ]


@app.get("/source/items")
def source_items(page: int = Query(default=1, ge=1), limit: int = Query(default=10, ge=1)) -> dict[str, Any]:
    global FAIL_SOURCE_PAGE_2_ONCE

    if page == 2 and FAIL_SOURCE_PAGE_2_ONCE:
        FAIL_SOURCE_PAGE_2_ONCE = False
        raise HTTPException(status_code=500, detail="Simulated transient failure on page 2")

    start = (page - 1) * limit
    end = start + limit
    items = SOURCE_ITEMS[start:end]
    next_page = page + 1 if end < len(SOURCE_ITEMS) else None
    return {"items": items, "next_page": next_page}


@app.post("/sink/items")
def sink_upsert(payload: SinkUpsert, idempotency_key: str | None = Header(default=None)) -> dict[str, Any]:
    global _sink_write_calls, IDEMPOTENCY_RECORDS

    payload_dict = payload.model_dump()
    payload_fingerprint = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))

    if idempotency_key:
        previous = IDEMPOTENCY_RECORDS.get(idempotency_key)
        if previous is not None:
            if previous["payload_fingerprint"] != payload_fingerprint:
                raise HTTPException(status_code=409, detail="Idempotency key reuse with different payload")
            return previous["response"]

    _sink_write_calls += 1

    # Simulate rate-limit sometimes
    if SINK_429_EVERY_N_CALLS > 0 and (_sink_write_calls % SINK_429_EVERY_N_CALLS == 0):
        # Retry-After is important to test respect for server hints
        raise HTTPException(status_code=429, detail="Simulated rate limit", headers={"Retry-After": "1"})

    external_id = payload.external_id
    created = external_id not in SINK_ITEMS_BY_EXTERNAL_ID
    SINK_ITEMS_BY_EXTERNAL_ID[external_id] = payload_dict

    response = {"status": "created" if created else "updated"}
    if idempotency_key:
        IDEMPOTENCY_RECORDS[idempotency_key] = {
            "payload_fingerprint": payload_fingerprint,
            "response": response,
        }

    return response


@app.get("/sink/items")
def sink_list() -> dict[str, Any]:
    # convenient for tests
    items = list(SINK_ITEMS_BY_EXTERNAL_ID.values())
    items.sort(key=lambda x: x["external_id"])
    return {"count": len(items), "items": items}


@app.post("/admin/reset")
def admin_reset() -> dict[str, Any]:
    global SINK_ITEMS_BY_EXTERNAL_ID, IDEMPOTENCY_RECORDS, FAIL_SOURCE_PAGE_2_ONCE, _sink_write_calls
    SINK_ITEMS_BY_EXTERNAL_ID = {}
    IDEMPOTENCY_RECORDS = {}
    FAIL_SOURCE_PAGE_2_ONCE = True
    _sink_write_calls = 0
    return {"ok": True}
