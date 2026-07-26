"""
Chaos matrix: node crash mid-write (ROADMAP Phase 5).

Phase 1 proved crash-safety exhaustively at the file level (truncate a
valid ledger.jsonl at every possible byte offset, confirm clean recovery).
This script proves the same property holds for a real OS-level SIGKILL
against a real live process under real concurrent write pressure — a
different, complementary kind of evidence: it can catch anything specific
to actual fsync timing, OS buffering, or process-death semantics that a
simulated file truncation can't, by construction, exercise.

Approach: hammer a live ledger service with rapid concurrent POST /ingest
calls from a background thread pool while the main thread kills the
process (SIGKILL, not a graceful shutdown) at a random moment. Restart
against the same data dir and verify: the process comes back up cleanly
(no crash on load), and the recovered event count is never less than the
number of requests that received a successful HTTP response before the
kill (fsync-before-response means an acknowledged write can never be lost)
and never more than the number of requests attempted (no phantom events).

Usage: python scripts/chaos_crash_mid_write.py [--iterations N]
"""
import argparse
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from harness_lib import REPO_ROOT, VENV_PYTHON

BASE_PORT = 8795
BASE_DATA_DIR = REPO_ROOT / "data" / "chaos_crash"


def start_ledger(data_dir: Path, port: int) -> subprocess.Popen:
    log = open(data_dir / "ledger.stdout.log", "a", encoding="utf-8")
    return subprocess.Popen(
        [
            str(VENV_PYTHON), "-m", "uvicorn",
            "ai_engine.ledger_service:get_app", "--factory",
            "--host", "127.0.0.1", "--port", str(port),
            "--app-dir", str(REPO_ROOT / "src"),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "AETHER_NODE_ID": "crashtest", "AETHER_DATA_DIR": str(data_dir)},
        stdout=log, stderr=subprocess.STDOUT,
    )


def wait_healthy(url: str, timeout_s: float = 10):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("ledger did not become healthy")


def hammer(
    url: str, stop_event: threading.Event, acknowledged: list, attempted: list, lock: threading.Lock
):
    i = 0
    while not stop_event.is_set():
        i += 1
        payload = {
            "node_id": "crashtest",
            "timestamp": "2026-01-01T00:00:00Z",
            "hazard_type": f"hazard-{i}",
            "severity": "HIGH",
            "coordinates": {"lat": 1.0, "lng": 2.0},
        }
        with lock:
            attempted.append(i)
        try:
            resp = httpx.post(f"{url}/ingest", json=payload, timeout=2.0)
            if resp.status_code == 200:
                with lock:
                    acknowledged.append(resp.json()["event_id"])
        except httpx.HTTPError:
            pass  # expected once the process is killed mid-request


def run_one_iteration(index: int) -> bool:
    print(f"\n--- iteration {index} ---")
    data_dir = BASE_DATA_DIR / f"iter{index}"
    data_dir.mkdir(parents=True)
    port = BASE_PORT + index  # distinct port per iteration — avoids Windows TIME_WAIT flakiness
    url = f"http://127.0.0.1:{port}"
    proc = start_ledger(data_dir, port)
    wait_healthy(url)

    stop_event = threading.Event()
    acknowledged: list = []
    attempted: list = []
    lock = threading.Lock()
    threads = [
        threading.Thread(target=hammer, args=(url, stop_event, acknowledged, attempted, lock))
        for _ in range(8)
    ]
    for t in threads:
        t.start()

    # This sandboxed environment's loopback networking has a fixed ~1s
    # per-request overhead (measured directly — not present when calling
    # Ledger in-process, so it's the HTTP/virtualized-network layer here,
    # not the ledger). The window needs to be wide enough for several
    # requests to actually land before the kill, or this test kills before
    # anything is even in flight and proves nothing.
    time.sleep(random.uniform(2.0, 4.0))
    proc.kill()  # SIGKILL / TerminateProcess — no graceful shutdown
    proc.wait(timeout=5)
    stop_event.set()
    for t in threads:
        t.join(timeout=5)

    print(f"killed after {len(acknowledged)} acknowledged writes ({len(attempted)} attempted)")

    restarted = start_ledger(data_dir, port)
    try:
        wait_healthy(url)
        vector = httpx.get(f"{url}/vector", timeout=5.0).json()
        recovered = sum(vector.values())
        print(f"recovered {recovered} events after restart")

        if recovered < len(acknowledged):
            print(f"FAIL: lost acknowledged writes ({recovered} < {len(acknowledged)})")
            return False
        if recovered > len(attempted):
            print(f"FAIL: phantom events ({recovered} > {len(attempted)} attempted)")
            return False
        print("OK: no acknowledged write lost, no phantom event created")
        return True
    finally:
        restarted.kill()
        restarted.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()

    if BASE_DATA_DIR.exists():
        shutil.rmtree(BASE_DATA_DIR)
    BASE_DATA_DIR.mkdir(parents=True)

    results = [run_one_iteration(i + 1) for i in range(args.iterations)]

    passed = sum(results)
    print(f"\n=== {passed}/{len(results)} iterations survived SIGKILL cleanly ===")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
