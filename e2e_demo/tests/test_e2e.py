from __future__ import annotations

import os
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_until_up(base_url: str, timeout_s: float = 10.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r = httpx.get(f"{base_url}/sink/items", timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("API did not become ready")


def start_api(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    # Start uvicorn as a subprocess
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "e2e_demo.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_sync(base_url: str, *extra_args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DEMO_BASE_URL"] = base_url
    return subprocess.run(
        [sys.executable, "-m", "e2e_demo.sync_tool.sync", *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )


def reset_api(base_url: str) -> None:
    r = httpx.post(f"{base_url}/admin/reset", timeout=5.0)
    r.raise_for_status()


def sink_state(base_url: str) -> dict:
    r = httpx.get(f"{base_url}/sink/items", timeout=5.0)
    r.raise_for_status()
    return r.json()


def test_e2e_sync_is_idempotent_and_handles_retries() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        # First run should create everything (with retries handling 500-once and 429 sometimes)
        r1 = run_sync(base_url)
        assert r1.returncode == 0, f"stdout={r1.stdout}\nstderr={r1.stderr}"

        s1 = sink_state(base_url)
        assert s1["count"] == 25

        # Second run should NOT create duplicates; count should remain 25
        r2 = run_sync(base_url)
        assert r2.returncode in (0, 2), f"stdout={r2.stdout}\nstderr={r2.stderr}"
        # Even if some writes failed transiently, we should not ever exceed 25.
        s2 = sink_state(base_url)
        assert s2["count"] == 25

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

def test_e2e_sync_limit() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        # Sync with limit of 5
        r = run_sync(base_url, "--limit", "5")
        assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

        s = sink_state(base_url)
        assert s["count"] == 5

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

def test_e2e_dry_run_report() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        # Run dry-run
        r = run_sync(base_url, "--dry-run")
        assert r.returncode == 0

        # Check report
        root = Path(__file__).parent.parent.parent
        report_path = root / "artifacts" / "superpowers" / "report.json"
        assert report_path.exists()

        with open(report_path, "r") as f:
            data = json.load(f)
            assert data["count"] == 25
            assert len(data["external_ids"]) <= 20
            assert "run_id" in data
            assert "timestamp" in data

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_sync_rejects_non_positive_limit() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        r = run_sync(base_url, "--limit", "-1")
        assert r.returncode == 2

        s = sink_state(base_url)
        assert s["count"] == 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_source_items_rejects_invalid_pagination_params() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        page_resp = httpx.get(f"{base_url}/source/items", params={"page": 0}, timeout=5.0)
        assert page_resp.status_code == 422

        limit_resp = httpx.get(f"{base_url}/source/items", params={"limit": 0}, timeout=5.0)
        assert limit_resp.status_code == 422
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_sink_idempotency_key_replay_and_conflict() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        key = "idem-1"
        payload = {"external_id": "item-1", "name": "Item 1", "value": 1}

        first = httpx.post(f"{base_url}/sink/items", json=payload, headers={"Idempotency-Key": key}, timeout=5.0)
        assert first.status_code == 200
        assert first.json() == {"status": "created"}

        replay = httpx.post(f"{base_url}/sink/items", json=payload, headers={"Idempotency-Key": key}, timeout=5.0)
        assert replay.status_code == 200
        assert replay.json() == {"status": "created"}

        conflict_payload = {"external_id": "item-1", "name": "Item 1 changed", "value": 9}
        conflict = httpx.post(
            f"{base_url}/sink/items",
            json=conflict_payload,
            headers={"Idempotency-Key": key},
            timeout=5.0,
        )
        assert conflict.status_code == 409

        state = sink_state(base_url)
        assert state["count"] == 1
        assert state["items"][0] == payload

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_source_paging_matches_parity_fixture() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        fixture_path = Path(__file__).parent / "fixtures" / "source_paging_parity.json"
        with open(fixture_path, "r") as f:
            fixture = json.load(f)

        def assert_case_response(response: httpx.Response, expected: dict, case_name: str) -> None:
            assert response.status_code == expected["status_code"], case_name
            payload = response.json()

            if "detail_contains" in expected:
                assert expected["detail_contains"] in payload.get("detail", ""), case_name
                return

            assert len(payload["items"]) == expected["count"], case_name
            assert payload["next_page"] == expected["next_page"], case_name

            if expected["count"] > 0:
                assert payload["items"][0]["external_id"] == expected["first_external_id"], case_name
                assert payload["items"][-1]["external_id"] == expected["last_external_id"], case_name

        for case in fixture["cases"]:
            if "requests" in case:
                for req in case["requests"]:
                    response = httpx.get(f"{base_url}/source/items", params=req["params"], timeout=5.0)
                    assert_case_response(response, req["expected"], case["name"])
            else:
                response = httpx.get(f"{base_url}/source/items", params=case["params"], timeout=5.0)
                assert_case_response(response, case["expected"], case["name"])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_sync_generates_trace_artifact() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    trace_dir = Path(__file__).parent.parent.parent / "artifacts" / "superpowers"
    before = set(trace_dir.glob("trace-*.json")) if trace_dir.exists() else set()

    proc = start_api(port)
    try:
        wait_until_up(base_url)
        reset_api(base_url)

        r = run_sync(base_url, "--limit", "3", "--retry-jitter-seed", "7")
        assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

        after = set(trace_dir.glob("trace-*.json"))
        created = after - before
        assert len(created) == 1

        trace_path = next(iter(created))
        with open(trace_path, "r") as f:
            trace = json.load(f)
        assert trace["outcome"] == "success"
        assert trace["exit_code"] == 0
        assert trace["retry_policy"]["jitter_seed"] == 7
        assert trace["fetched_count"] == 3
        assert isinstance(trace["events"], list)
        assert len(trace["events"]) >= 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_sync_failure_generates_trace_artifact() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    trace_dir = Path(__file__).parent.parent.parent / "artifacts" / "superpowers"
    before = set(trace_dir.glob("trace-*.json")) if trace_dir.exists() else set()

    r = run_sync(
        base_url,
        "--retry-max-attempts",
        "1",
        "--retry-base-delay-s",
        "0.01",
        "--retry-max-delay-s",
        "0.01",
        "--retry-jitter-seed",
        "5",
    )
    assert r.returncode == 3, f"stdout={r.stdout}\nstderr={r.stderr}"

    after = set(trace_dir.glob("trace-*.json"))
    created = after - before
    assert len(created) == 1

    trace_path = next(iter(created))
    with open(trace_path, "r") as f:
        trace = json.load(f)

    assert trace["outcome"] == "failure"
    assert trace["exit_code"] == 3
    assert trace["error_category"] == "transient_retry_exhausted"
    assert trace["fetched_count"] == 0
    assert isinstance(trace["events"], list)
