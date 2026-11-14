import assert from "node:assert/strict";
import test from "node:test";
import { applyDelta, type Snapshot } from "./stream.ts";

test("duplicate ignored; gap forces snapshot", () => {
  const snap: Snapshot = { exam_id: "e", stream_seq: 2, readiness: "Ready", sessions: [{ session_id: "s1", lifecycle: "READY" }] };
  const dup = applyDelta(snap, { exam_id: "e", stream_seq: 2, op: "heartbeat" });
  assert.equal((dup as Snapshot).stream_seq, 2);
  assert.equal(applyDelta(snap, { exam_id: "e", stream_seq: 4, op: "heartbeat" }), "resnapshot");
  const next = applyDelta(snap, { exam_id: "e", stream_seq: 3, op: "upsert", session_id: "s1", patch: { lifecycle: "IN_EXAM" } }) as Snapshot;
  assert.equal(next.sessions[0].lifecycle, "IN_EXAM");
  assert.equal(next.stream_seq, 3);
});
