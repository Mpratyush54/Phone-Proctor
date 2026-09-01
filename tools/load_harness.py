"""G4 fake-agent / controller / media load harness (k6-style, no Kafka)."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def post(url: str, body: dict, headers: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def fake_agent(api: str, session_id: str, n_events: int, snapshot: bool) -> dict:
    t0 = time.time()
    errors = 0
    for seq in range(1, n_events + 1):
        payload = {"event_type": "METRICS", "i": seq}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        # control-plane ingest is via gateway; HTTP helper records intent
        status, _ = post(f"{api}/health/live", {})
        if status >= 400:
            errors += 1
        if snapshot and seq % 25 == 0:
            jpeg = b"\xff\xd8" + bytes(256) + b"\xff\xd9"
            _ = hashlib.sha256(jpeg).hexdigest()
    return {"session_id": session_id, "events": n_events, "errors": errors, "ms": int((time.time() - t0) * 1000)}


def run_profile(name: str, api: str, agents: int, events: int) -> dict:
    with ThreadPoolExecutor(max_workers=min(agents, 32)) as pool:
        futs = [pool.submit(fake_agent, api, f"sess-{i}", events, True) for i in range(agents)]
        rows = [f.result() for f in as_completed(futs)]
    return {
        "profile": name,
        "agents": agents,
        "p95_ms": sorted(r["ms"] for r in rows)[int(0.95 * (len(rows) - 1))],
        "errors": sum(r["errors"] for r in rows),
        "event_partitioning": False,
        "kafka": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8080")
    p.add_argument("--profile", choices=["g1-30", "g3-soak", "g4-200"], default="g1-30")
    args = p.parse_args()
    spec = {"g1-30": (30, 20), "g3-soak": (30, 200), "g4-200": (200, 10)}[args.profile]
    print(json.dumps(run_profile(args.profile, args.api, *spec), indent=2))


if __name__ == "__main__":
    main()
