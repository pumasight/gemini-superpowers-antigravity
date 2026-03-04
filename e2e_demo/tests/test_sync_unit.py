from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import httpx
import pytest

from e2e_demo.sync_tool.sync import (
    EXIT_HARD_HTTP_FAILURE,
    EXIT_PARTIAL_FAILURE,
    EXIT_TRANSIENT_EXHAUSTED,
    RetryPolicy,
    backoff,
    build_retry_policy,
    classify_run_exception,
    fetch_all_source_items,
    map_source_item_to_sink_payload,
    parse_retry_after_seconds,
    request_with_retries,
    write_trace_artifact,
)


class _MockResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None, payload: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "mock error",
                request=httpx.Request("GET", "http://example.test"),
                response=httpx.Response(self.status_code),
            )


class _SequenceClient:
    def __init__(self, sequence: list[object]):
        self._sequence = sequence
        self.calls = 0

    def request(self, method: str, url: str, headers=None, json=None):
        item = self._sequence[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def test_parse_retry_after_clamps_numeric_values() -> None:
    assert parse_retry_after_seconds("-5", cap=3.0) == 0.0
    assert parse_retry_after_seconds("100", cap=3.0) == 3.0


def test_request_with_retries_retries_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("e2e_demo.sync_tool.sync.time.sleep", lambda s: sleeps.append(s))

    client = _SequenceClient(
        [
            httpx.RemoteProtocolError("connection dropped"),
            _MockResponse(200, payload={"ok": True}),
        ]
    )

    response = request_with_retries(
        client,  # type: ignore[arg-type]
        "GET",
        "http://example.test/resource",
        retry=RetryPolicy(max_attempts=2, base_delay_s=0.01, max_delay_s=0.02),
        run_id="t1",
    )

    assert response.status_code == 200
    assert client.calls == 2
    assert len(sleeps) == 1


def test_fetch_all_source_items_raises_when_page_cap_exceeded() -> None:
    pages = [_MockResponse(200, payload={"items": [{"external_id": "x", "name": "x", "value": 1}], "next_page": i + 2}) for i in range(100)]
    client = _SequenceClient(pages)

    with pytest.raises(RuntimeError, match="Pagination exceeded max pages"):
        fetch_all_source_items(client, "http://example.test", run_id="t2", retry_policy=RetryPolicy())  # type: ignore[arg-type]


def test_classify_run_exception_transient_transport() -> None:
    category, code = classify_run_exception(httpx.ReadTimeout("timed out"))
    assert category == "transient_retry_exhausted"
    assert code == EXIT_TRANSIENT_EXHAUSTED


def test_classify_run_exception_transient_http() -> None:
    resp = httpx.Response(503, request=httpx.Request("GET", "http://example.test"))
    err = httpx.HTTPStatusError("server busy", request=resp.request, response=resp)
    category, code = classify_run_exception(err)
    assert category == "transient_retry_exhausted"
    assert code == EXIT_TRANSIENT_EXHAUSTED


def test_classify_run_exception_hard_http() -> None:
    resp = httpx.Response(400, request=httpx.Request("GET", "http://example.test"))
    err = httpx.HTTPStatusError("bad request", request=resp.request, response=resp)
    category, code = classify_run_exception(err)
    assert category == "hard_http_failure"
    assert code == EXIT_HARD_HTTP_FAILURE


def test_classify_run_exception_validation() -> None:
    category, code = classify_run_exception(KeyError("external_id"))
    assert category == "validation_failure"
    assert code == EXIT_PARTIAL_FAILURE


def test_build_retry_policy_valid() -> None:
    policy = build_retry_policy(7, 0.2, 2.0, jitter_seed=123)
    assert policy.max_attempts == 7
    assert policy.base_delay_s == 0.2
    assert policy.max_delay_s == 2.0
    assert policy.jitter_seed == 123


def test_build_retry_policy_rejects_bad_bounds() -> None:
    with pytest.raises(ValueError, match="max delay must be >= retry base delay"):
        build_retry_policy(4, 1.0, 0.5)


def test_backoff_is_deterministic_with_seeded_rng() -> None:
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    seq1 = [backoff(attempt=i, base=0.4, cap=5.0, rng=rng1) for i in (1, 2, 3)]
    seq2 = [backoff(attempt=i, base=0.4, cap=5.0, rng=rng2) for i in (1, 2, 3)]
    assert seq1 == seq2


def test_http_request_log_schema(caplog: pytest.LogCaptureFixture) -> None:
    client = _SequenceClient([_MockResponse(200, payload={"ok": True})])

    with caplog.at_level(logging.INFO, logger="sync_tool"):
        request_with_retries(
            client,  # type: ignore[arg-type]
            "GET",
            "http://example.test/resource",
            retry=RetryPolicy(max_attempts=2, base_delay_s=0.01, max_delay_s=0.02),
            run_id="run-123",
        )

    matching = [r for r in caplog.records if r.getMessage() == "http_request"]
    assert len(matching) == 1
    record = matching[0]

    for field in ("run_id", "method", "url", "status", "elapsed_ms", "attempt"):
        assert hasattr(record, field), f"missing field in log record: {field}"

    assert isinstance(record.run_id, str)
    assert isinstance(record.method, str)
    assert isinstance(record.url, str)
    assert isinstance(record.status, int)
    assert isinstance(record.elapsed_ms, int)
    assert isinstance(record.attempt, int)


def test_map_source_item_to_sink_payload_valid() -> None:
    payload = map_source_item_to_sink_payload({"external_id": "item-1", "name": "Item 1", "value": "7"})
    assert payload == {"external_id": "item-1", "name": "Item 1", "value": 7}


def test_map_source_item_to_sink_payload_missing_field() -> None:
    with pytest.raises(ValueError, match="missing required field: name"):
        map_source_item_to_sink_payload({"external_id": "item-1", "value": 7})


def test_map_source_item_to_sink_payload_bad_value_type() -> None:
    with pytest.raises(ValueError, match="value must be an integer"):
        map_source_item_to_sink_payload({"external_id": "item-1", "name": "Item 1", "value": True})


def test_write_trace_artifact_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("e2e_demo.sync_tool.sync.find_repo_root", lambda _: tmp_path)
    path = write_trace_artifact(
        run_id="run123",
        base_url="http://example.test",
        retry_policy=RetryPolicy(max_attempts=2, base_delay_s=0.1, max_delay_s=1.0, jitter_seed=9),
        events=[{"event": "http_request", "status": 200}],
        exit_code=0,
        error_category=None,
        fetched_count=3,
        stats={"created_count": 3, "updated_count": 0, "failed_count": 0},
    )
    assert path.exists()

    payload = json.loads(path.read_text())
    assert payload["outcome"] == "success"
    assert payload["exit_code"] == 0
    assert payload["retry_policy"]["jitter_seed"] == 9
    assert len(payload["events"]) == 1


def test_write_trace_artifact_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("e2e_demo.sync_tool.sync.find_repo_root", lambda _: tmp_path)
    path = write_trace_artifact(
        run_id="run124",
        base_url="http://example.test",
        retry_policy=RetryPolicy(),
        events=[],
        exit_code=3,
        error_category="transient_retry_exhausted",
        fetched_count=0,
        stats=None,
    )
    payload = json.loads(path.read_text())
    assert payload["outcome"] == "failure"
    assert payload["error_category"] == "transient_retry_exhausted"
