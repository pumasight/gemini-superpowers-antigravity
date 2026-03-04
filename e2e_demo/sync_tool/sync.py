from __future__ import annotations

import argparse
import os
import random
import time
import uuid
import logging
import json
import email.utils
from dataclasses import dataclass
from typing import Any
from pathlib import Path

import httpx


LOG = logging.getLogger("sync_tool")

EXIT_OK = 0
EXIT_PARTIAL_FAILURE = 2
EXIT_TRANSIENT_EXHAUSTED = 3
EXIT_HARD_HTTP_FAILURE = 4
EXIT_UNEXPECTED_FAILURE = 5


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def env_or_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


def find_repo_root(start_path: Path) -> Path:
    """Traverse upwards to find the repository root (containing .agent/)."""
    curr = start_path.resolve()
    for _ in range(10):  # limit search depth
        if (curr / ".agent").exists():
            return curr
        if curr.parent == curr:
            break
        curr = curr.parent
    # Fallback to current working directory if not found
    return Path.cwd()


@dataclass
class RetryPolicy:
    max_attempts: int = 6
    base_delay_s: float = 0.4
    max_delay_s: float = 5.0
    jitter_seed: int | None = None


def build_retry_policy(max_attempts: int, base_delay_s: float, max_delay_s: float, jitter_seed: int | None = None) -> RetryPolicy:
    if max_attempts <= 0:
        raise ValueError("retry max attempts must be > 0")
    if base_delay_s <= 0:
        raise ValueError("retry base delay must be > 0")
    if max_delay_s <= 0:
        raise ValueError("retry max delay must be > 0")
    if max_delay_s < base_delay_s:
        raise ValueError("retry max delay must be >= retry base delay")
    return RetryPolicy(max_attempts=max_attempts, base_delay_s=base_delay_s, max_delay_s=max_delay_s, jitter_seed=jitter_seed)


def backoff(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    # exponential backoff with jitter
    delay = min(cap, base * (2 ** (attempt - 1)))
    jitter_source = rng.random if rng is not None else random.random
    return delay * (0.5 + jitter_source())  # jitter in [0.5, 1.5)


def parse_retry_after_seconds(raw_value: str, cap: float) -> float:
    try:
        seconds = float(raw_value)
        return min(cap, max(0.0, seconds))
    except ValueError:
        parsed_dt = email.utils.parsedate_to_datetime(raw_value)
        if parsed_dt is None:
            raise ValueError("Invalid Retry-After header")
        delay = parsed_dt.timestamp() - time.time()
        return min(cap, max(0.0, delay))


def should_retry(status_code: int) -> bool:
    if status_code == 429:
        return True
    if 500 <= status_code <= 599:
        return True
    if status_code in (408,):
        return True
    return False


def classify_run_exception(exc: Exception) -> tuple[str, int]:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ("transient_retry_exhausted", EXIT_TRANSIENT_EXHAUSTED)

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else None
        if status is not None and should_retry(status):
            return ("transient_retry_exhausted", EXIT_TRANSIENT_EXHAUSTED)
        return ("hard_http_failure", EXIT_HARD_HTTP_FAILURE)

    if isinstance(exc, (KeyError, TypeError, ValueError, argparse.ArgumentTypeError)):
        return ("validation_failure", EXIT_PARTIAL_FAILURE)

    return ("unexpected_error", EXIT_UNEXPECTED_FAILURE)


def request_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: Any | None = None,
    retry: RetryPolicy,
    run_id: str,
    trace_events: list[dict[str, Any]] | None = None,
) -> httpx.Response:
    last_exc: Exception | None = None
    rng = random.Random(retry.jitter_seed) if retry.jitter_seed is not None else None

    for attempt in range(1, retry.max_attempts + 1):
        try:
            t0 = time.time()
            resp = client.request(method, url, headers=headers, json=json)
            elapsed_ms = int((time.time() - t0) * 1000)

            LOG.info(
                "http_request",
                extra={
                    "run_id": run_id,
                    "method": method,
                    "url": url,
                    "status": resp.status_code,
                    "elapsed_ms": elapsed_ms,
                    "attempt": attempt,
                },
            )
            if trace_events is not None:
                trace_events.append(
                    {
                        "event": "http_request",
                        "run_id": run_id,
                        "method": method,
                        "url": url,
                        "status": resp.status_code,
                        "elapsed_ms": elapsed_ms,
                        "attempt": attempt,
                    }
                )

            if resp.status_code < 400:
                return resp

            if should_retry(resp.status_code) and attempt < retry.max_attempts:
                # Respect Retry-After for 429 if present
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        sleep_s = parse_retry_after_seconds(retry_after, retry.max_delay_s)
                    except ValueError:
                        sleep_s = backoff(attempt, retry.base_delay_s, retry.max_delay_s, rng)
                else:
                    sleep_s = backoff(attempt, retry.base_delay_s, retry.max_delay_s, rng)

                if trace_events is not None:
                    trace_events.append(
                        {
                            "event": "retry_sleep",
                            "run_id": run_id,
                            "method": method,
                            "url": url,
                            "attempt": attempt,
                            "sleep_s": sleep_s,
                            "status": resp.status_code,
                        }
                    )
                time.sleep(sleep_s)
                continue

            resp.raise_for_status()
            return resp  # unreachable normally

        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            LOG.warning("transient_network_error", extra={"run_id": run_id, "attempt": attempt, "error": str(e)})
            if trace_events is not None:
                trace_events.append(
                    {
                        "event": "transient_network_error",
                        "run_id": run_id,
                        "method": method,
                        "url": url,
                        "attempt": attempt,
                        "error": str(e),
                    }
                )
            if attempt >= retry.max_attempts:
                raise
            time.sleep(backoff(attempt, retry.base_delay_s, retry.max_delay_s, rng))

    if last_exc:
        raise last_exc
    raise RuntimeError("request_with_retries failed unexpectedly")


def fetch_all_source_items(
    client: httpx.Client,
    base_url: str,
    *,
    run_id: str,
    retry_policy: RetryPolicy,
    trace_events: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        return []

    items: list[dict[str, Any]] = []
    page = 1
    page_size = 10
    max_pages = 100

    while page and page <= max_pages:
        url = f"{base_url}/source/items?page={page}&limit={page_size}"
        resp = request_with_retries(client, "GET", url, retry=retry_policy, run_id=run_id, trace_events=trace_events)
        data = resp.json()
        batch = data["items"]
        items.extend(batch)

        if limit is not None and len(items) >= limit:
            page = None
            break

        page = data.get("next_page")

    if page:
        raise RuntimeError(f"Pagination exceeded max pages ({max_pages})")

    if limit is not None:
        items = items[:limit]

    return items


def map_source_item_to_sink_payload(source_item: dict[str, Any]) -> dict[str, Any]:
    required = ("external_id", "name", "value")
    for key in required:
        if key not in source_item:
            raise ValueError(f"source item missing required field: {key}")

    external_id = source_item["external_id"]
    if not isinstance(external_id, str) or not external_id.strip():
        raise ValueError("source item field external_id must be a non-empty string")

    name = source_item["name"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError("source item field name must be a non-empty string")

    raw_value = source_item["value"]
    if isinstance(raw_value, bool):
        raise ValueError("source item field value must be an integer")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("source item field value must be an integer") from exc

    return {
        "external_id": external_id,
        "name": name,
        "value": value,
    }


def upsert_sink_items(
    client: httpx.Client,
    base_url: str,
    source_items: list[dict[str, Any]],
    *,
    run_id: str,
    retry_policy: RetryPolicy,
    trace_events: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    created = 0
    updated = 0
    failed = 0

    for it in source_items:
        try:
            payload = map_source_item_to_sink_payload(it)

            # idempotency hint: deterministic key per external_id for safe repeats
            headers = {"Idempotency-Key": f"sync:{payload['external_id']}"}

            resp = request_with_retries(
                client,
                "POST",
                f"{base_url}/sink/items",
                headers=headers,
                json=payload,
                retry=retry_policy,
                run_id=run_id,
                trace_events=trace_events,
            )
            status = resp.json()["status"]
            if status == "created":
                created += 1
            else:
                updated += 1
        except Exception as e:
            failed += 1
            LOG.error("upsert_failed", extra={"run_id": run_id, "external_id": payload["external_id"], "error": str(e)})

    return {"created_count": created, "updated_count": updated, "failed_count": failed}


def write_trace_artifact(
    *,
    run_id: str,
    base_url: str,
    retry_policy: RetryPolicy,
    events: list[dict[str, Any]],
    exit_code: int,
    error_category: str | None,
    fetched_count: int,
    stats: dict[str, int] | None,
) -> Path:
    root = find_repo_root(Path(__file__))
    report_dir = root / "artifacts" / "superpowers"
    report_dir.mkdir(parents=True, exist_ok=True)
    trace_path = report_dir / f"trace-{run_id}.json"

    trace = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base_url,
        "retry_policy": {
            "max_attempts": retry_policy.max_attempts,
            "base_delay_s": retry_policy.base_delay_s,
            "max_delay_s": retry_policy.max_delay_s,
            "jitter_seed": retry_policy.jitter_seed,
        },
        "outcome": "success" if exit_code == EXIT_OK else "failure",
        "exit_code": exit_code,
        "error_category": error_category,
        "fetched_count": fetched_count,
        "stats": stats,
        "events": events,
    }

    with open(trace_path, "w") as f:
        json.dump(trace, f, indent=2)

    return trace_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=positive_int, default=None, help="Maximum number of items to process")
    parser.add_argument(
        "--retry-max-attempts",
        type=positive_int,
        default=None,
        help="Max retry attempts for transient failures",
    )
    parser.add_argument(
        "--retry-base-delay-s",
        type=positive_float,
        default=None,
        help="Base retry delay in seconds",
    )
    parser.add_argument(
        "--retry-max-delay-s",
        type=positive_float,
        default=None,
        help="Max retry delay cap in seconds",
    )
    parser.add_argument(
        "--retry-jitter-seed",
        type=int,
        default=None,
        help="Optional deterministic jitter seed (primarily for tests/CI)",
    )
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:10]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    retry_max_attempts = (
        args.retry_max_attempts
        if args.retry_max_attempts is not None
        else positive_int(env_or_default("SYNC_RETRY_MAX_ATTEMPTS", str(RetryPolicy.max_attempts)))
    )
    retry_base_delay_s = (
        args.retry_base_delay_s
        if args.retry_base_delay_s is not None
        else positive_float(env_or_default("SYNC_RETRY_BASE_DELAY_S", str(RetryPolicy.base_delay_s)))
    )
    retry_max_delay_s = (
        args.retry_max_delay_s
        if args.retry_max_delay_s is not None
        else positive_float(env_or_default("SYNC_RETRY_MAX_DELAY_S", str(RetryPolicy.max_delay_s)))
    )
    retry_jitter_seed = (
        args.retry_jitter_seed
        if args.retry_jitter_seed is not None
        else parse_optional_int(os.environ.get("SYNC_RETRY_JITTER_SEED"))
    )

    LOG.info("run_start", extra={"run_id": run_id, "base_url": args.base_url})

    timeout = httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=10.0)
    retry_policy = build_retry_policy(
        max_attempts=retry_max_attempts,
        base_delay_s=retry_base_delay_s,
        max_delay_s=retry_max_delay_s,
        jitter_seed=retry_jitter_seed,
    )
    trace_events: list[dict[str, Any]] = []
    fetched_count = 0
    stats: dict[str, int] | None = None
    exit_code = EXIT_UNEXPECTED_FAILURE
    error_category: str | None = None
    try:
        with httpx.Client(timeout=timeout) as client:
            items = fetch_all_source_items(
                client,
                args.base_url,
                run_id=run_id,
                retry_policy=retry_policy,
                trace_events=trace_events,
                limit=args.limit,
            )
            LOG.info("fetched_source", extra={"run_id": run_id, "count": len(items)})
            fetched_count = len(items)

            if args.dry_run:
                root = find_repo_root(Path(__file__))
                report_dir = root / "artifacts" / "superpowers"
                report_dir.mkdir(parents=True, exist_ok=True)
                report_path = report_dir / "report.json"

                report = {
                    "run_id": run_id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "count": len(items),
                    "external_ids": [it["external_id"] for it in items[:20]],
                }

                with open(report_path, "w") as f:
                    json.dump(report, f, indent=2)

                LOG.info("dry_run_report_generated", extra={"run_id": run_id, "path": str(report_path)})
                LOG.info("dry_run_no_writes", extra={"run_id": run_id})
                exit_code = EXIT_OK
                return exit_code

            stats = upsert_sink_items(
                client,
                args.base_url,
                items,
                run_id=run_id,
                retry_policy=retry_policy,
                trace_events=trace_events,
            )
            LOG.info("run_summary", extra={"run_id": run_id, **stats, "fetched_count": len(items)})

        if stats["failed_count"] > 0:
            LOG.error(
                "run_error",
                extra={
                    "run_id": run_id,
                    "error_category": "validation_failure",
                    "exit_code": EXIT_PARTIAL_FAILURE,
                    "failed_count": stats["failed_count"],
                },
            )
            exit_code = EXIT_PARTIAL_FAILURE
            error_category = "validation_failure"
            return exit_code
        exit_code = EXIT_OK
        return exit_code
    except Exception as exc:
        category, exit_code = classify_run_exception(exc)
        error_category = category
        LOG.error("run_error", extra={"run_id": run_id, "error_category": category, "exit_code": exit_code, "error": str(exc)})
        return exit_code
    finally:
        try:
            trace_path = write_trace_artifact(
                run_id=run_id,
                base_url=args.base_url,
                retry_policy=retry_policy,
                events=trace_events,
                exit_code=exit_code,
                error_category=error_category,
                fetched_count=fetched_count,
                stats=stats,
            )
            LOG.info("trace_artifact_generated", extra={"run_id": run_id, "path": str(trace_path)})
        except Exception as trace_exc:
            LOG.error("trace_artifact_failed", extra={"run_id": run_id, "error": str(trace_exc)})


if __name__ == "__main__":
    raise SystemExit(main())
