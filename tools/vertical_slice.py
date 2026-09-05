#!/usr/bin/env python3
"""Activation vertical slice against the control-plane API (stdlib urllib only).

Flow: live -> dev-login -> exam/open/roster -> token/enroll -> EXAM_START -> snapshot.

Usage:
  API_URL=http://127.0.0.1:8080 python3 tools/vertical_slice.py

If API_URL is unset, probes http://127.0.0.1:18080 then http://127.0.0.1:8080.
Exits non-zero with a clear error when the API is down (does not hang).
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

TIMEOUT_S = 3.0
DEFAULT_BASES = ("http://127.0.0.1:18080", "http://127.0.0.1:8080")


class SliceError(Exception):
    pass


def _opener():
    return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request(
    opener,
    method: str,
    url: str,
    body: dict | None = None,
    headers: dict | None = None,
    timeout: float = TIMEOUT_S,
) -> Any:
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"content-type": "application/json", **(headers or {})}
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        raise SliceError(f"{method} {url} failed: HTTP {e.code} {payload}") from e
    except TimeoutError as e:
        raise SliceError(f"timed out after {timeout}s connecting to {url}") from e
    except URLError as e:
        reason = getattr(e, "reason", e)
        raise SliceError(f"API is not running at {url} ({reason})") from e


def probe_live(opener, base: str) -> None:
    live = request(opener, "GET", f"{base}/health/live")
    if live.get("status") != "live":
        raise SliceError(f"unexpected /health/live response from {base}: {live}")


def resolve_base(opener) -> str:
    env = os.environ.get("API_URL", "").strip().rstrip("/")
    if env:
        probe_live(opener, env)
        return env
    errors: list[str] = []
    for base in DEFAULT_BASES:
        try:
            probe_live(opener, base)
            return base
        except SliceError as e:
            errors.append(str(e))
    raise SliceError(
        "API is not running at http://127.0.0.1:18080 or http://127.0.0.1:8080. "
        + "; ".join(errors)
    )


def run() -> dict[str, Any]:
    opener = _opener()
    base = resolve_base(opener)
    csrf_headers: dict[str, str] = {}

    login = request(opener, "POST", f"{base}/api/v1/auth/dev-login", {})
    csrf = login.get("csrf")
    if not csrf:
        raise SliceError(f"dev-login did not return csrf: {login}")
    csrf_headers["x-csrf-token"] = str(csrf)

    code = f"VS-{uuid.uuid4().hex[:8]}"
    exam = request(
        opener,
        "POST",
        f"{base}/api/v1/exams",
        {"code": code, "title": code, "policy": {"camera": True, "microphone": True}},
        csrf_headers,
    )
    exam_id = exam.get("id")
    if not exam_id:
        raise SliceError(f"create exam did not return id: {exam}")

    request(opener, "POST", f"{base}/api/v1/exams/{exam_id}/open", {}, csrf_headers)

    roster = request(
        opener,
        "POST",
        f"{base}/api/v1/exams/{exam_id}/roster",
        {"rows": [{"student_external_id": "s1", "display_name": "Ada"}]},
        csrf_headers,
    )
    results = roster.get("results") or []
    enrollment_id = next((r.get("id") for r in results if r.get("ok") and r.get("id")), None)
    if not enrollment_id:
        raise SliceError(f"roster import did not return enrollment id: {roster}")

    issued = request(opener, "POST", f"{base}/api/v1/enrollments/{enrollment_id}/token", {}, csrf_headers)
    token = issued.get("token")
    if not token:
        raise SliceError(f"token issue did not return token: {issued}")

    enrolled = request(opener, "POST", f"{base}/api/v1/enroll", {"token": token, "fingerprint": "fp"})
    session_id = enrolled.get("session_id")
    if not session_id:
        raise SliceError(f"enroll did not return session_id: {enrolled}")

    request(
        opener,
        "POST",
        f"{base}/api/v1/sessions/{session_id}/commands",
        {"type": "EXAM_START", "idempotency_key": str(uuid.uuid4())},
        csrf_headers,
    )

    snap = request(opener, "GET", f"{base}/api/v1/console/snapshot?exam_id={exam_id}")
    if snap.get("exam_id") != exam_id:
        raise SliceError(f"snapshot exam_id mismatch: {snap}")

    return {"ok": True, "session_id": session_id, "exam_id": exam_id}


def main() -> int:
    try:
        summary = run()
    except SliceError as e:
        print(f"vertical_slice failed: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
