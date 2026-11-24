import assert from "node:assert/strict";
import test from "node:test";
import { applyDelta, applyDeltas, type Snapshot } from "./stream";

test("duplicate ignored; gap forces snapshot", () => {
  const snap: Snapshot = { exam_id: "e", stream_seq: 2, readiness: "Ready", sessions: [{ session_id: "s1", lifecycle: "READY" }] };
  const dup = applyDelta(snap, { exam_id: "e", stream_seq: 2, op: "heartbeat" });
  assert.equal((dup as Snapshot).stream_seq, 2);
  assert.equal(applyDelta(snap, { exam_id: "e", stream_seq: 4, op: "heartbeat" }), "resnapshot");
  const next = applyDelta(snap, { exam_id: "e", stream_seq: 3, op: "upsert", session_id: "s1", patch: { lifecycle: "IN_EXAM" } }) as Snapshot;
  assert.equal(next.sessions[0].lifecycle, "IN_EXAM");
  assert.equal(next.stream_seq, 3);
});

test("batched deltas add new candidates, update state, and remove sessions", () => {
  const original: Snapshot = { exam_id: "e", stream_id: "boot", stream_seq: 0, readiness: "Ready", sessions: [] };
  const next = applyDeltas(original, {
    stream_id: "boot", stream_seq: 2, readiness: "Degraded",
    items: [
      { exam_id: "e", stream_seq: 1, op: "upsert", session_id: "new", patch: { lifecycle: "READY", connectivity: "offline" } },
      { exam_id: "e", stream_seq: 2, op: "upsert", session_id: "new", patch: { connectivity: "online" } },
    ],
  });
  assert.notEqual(next, "resnapshot");
  const current = next as Snapshot;
  assert.deepEqual(current.sessions, [{ session_id: "new", lifecycle: "READY", connectivity: "online" }]);
  assert.equal(current.readiness, "Degraded");
  assert.equal(original.sessions.length, 0);
  const removed = applyDelta(current, { exam_id: "e", stream_seq: 3, op: "remove", session_id: "new" });
  assert.deepEqual((removed as Snapshot).sessions, []);
});

test("stream restarts and incomplete additions require a new snapshot", () => {
  const snapshot: Snapshot = { exam_id: "e", stream_id: "old", stream_seq: 1, readiness: "Ready", sessions: [] };
  assert.equal(applyDeltas(snapshot, { stream_id: "new", stream_seq: 1, items: [] }), "resnapshot");
  assert.equal(applyDeltas(snapshot, { stream_id: "old", stream_seq: 0, items: [] }), "resnapshot");
  assert.equal(applyDelta(snapshot, { exam_id: "e", stream_seq: 2, op: "upsert", session_id: "unknown", patch: { connectivity: "online" } }), "resnapshot");
});
