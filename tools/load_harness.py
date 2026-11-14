"""G4 fake-agent / controller / media load harness (k6-style, no Kafka)."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener


def request(opener, method: str, url: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, method=method, headers={"content-type": "application/json", **(headers or {})})
    try:
        with opener.open(req, timeout=8) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return e.code, parsed


def staff_session(api: str):
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    status, body = request(opener, "POST", f"{api}/api/v1/auth/dev-login", {})
    if status >= 400:
        raise RuntimeError(f"dev-login {status} {body}")
    return opener, body["csrf"]


def ingest_one(opener, api: str, csrf: str, session_id: str, n_events: int) -> dict:
    t0 = time.time()
    errors = 0
    for seq in range(1, n_events + 1):
        payload = {"event_type": "METRICS", "i": seq}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        status, _ = request(
            opener,
            "POST",
            f"{api}/api/v1/dev/ingest",
            {"session_id": session_id, "seq": seq, "batch_id": f"{session_id}:{seq}", "hash": digest, "payload": payload},
            {"x-csrf-token": csrf},
        )
        if status >= 400:
            errors += 1
    return {"session_id": session_id, "events": n_events, "errors": errors, "ms": int((time.time() - t0) * 1000)}


def run_profile(name: str, api: str, agents: int, events: int) -> dict:
    opener, csrf = staff_session(api)
    headers = {"x-csrf-token": csrf}
    st, exam = request(opener, "POST", f"{api}/api/v1/exams", {"code": f"LOAD-{int(time.time())}", "title": name}, headers)
    if st >= 400:
        raise RuntimeError(f"exam {st} {exam}")
    exam_id = exam["id"]
    rows = [{"student_external_id": str(i), "display_name": f"S{i}"} for i in range(agents)]
    st, roster = request(opener, "POST", f"{api}/api/v1/exams/{exam_id}/roster", {"rows": rows}, headers)
    session_ids = []
    for row in roster.get("results") or []:
        if not row.get("ok"):
            continue
        _, tok = request(opener, "POST", f"{api}/api/v1/enrollments/{row['id']}/token", {}, headers)
        _, cred = request(opener, "POST", f"{api}/api/v1/enroll", {"token": tok["token"], "fingerprint": row["id"]}, headers)
        session_ids.append(cred["session_id"])
    with ThreadPoolExecutor(max_workers=min(max(agents, 1), 32)) as pool:
        futs = [pool.submit(ingest_one, opener, api, csrf, sid, events) for sid in session_ids]
        out = [f.result() for f in as_completed(futs)]
    times = sorted(r["ms"] for r in out) or [0]
    return {
        "profile": name,
        "agents": len(session_ids),
        "p95_ms": times[int(0.95 * (len(times) - 1))],
        "errors": sum(r["errors"] for r in out),
        "event_partitioning": False,
        "kafka": False,
        "exam_id": exam_id,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8080")
    p.add_argument("--profile", choices=["g1-30", "g3-soak", "g4-200"], default="g1-30")
    args = p.parse_args()
    spec = {"g1-30": (30, 20), "g3-soak": (30, 50), "g4-200": (200, 10)}[args.profile]
    print(json.dumps(run_profile(args.profile, args.api, *spec), indent=2))


if __name__ == "__main__":
    main()
