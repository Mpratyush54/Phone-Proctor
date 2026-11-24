import { randomUUID } from "node:crypto";
import assert from "node:assert/strict";
import test from "node:test";
import { Store } from "../src/store.js";
import { loadConfig } from "../src/config.js";
import { ConsoleStream } from "../src/console-stream.js";

function staff(store: Store) {
  const seeded = store.seedDev();
  return store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
}

test("stable snapshot pages cover 1,000 sessions; event log is bounded; kafka stays off", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, `SCALE-${randomUUID()}`, "s", {});
  const rows = Array.from({ length: 1000 }, (_, i) => ({ student_external_id: String(i), display_name: `S${i}` }));
  store.importRoster(ctx, exam.id, rows);
  for (const en of store.enrollments.values()) {
    store.redeemEnrollment(store.issueToken(ctx, en.id).token, "fp-" + en.id);
  }
  const page = store.snapshot(exam.id, { cursor: 0, limit: 600 });
  assert.equal(page.sessions.length, 500);
  assert.equal(page.next_cursor, 500);
  assert.equal(page.total, 1000);
  const sid = page.sessions[0].session_id;
  store.updateConnectivity(sid, "online");
  store.updateConnectivity(sid, "online");
  const second = store.snapshot(exam.id, { cursor: page.next_cursor, limit: 500 });
  assert.equal(second.next_cursor, 1000);
  assert.equal(second.stream_id, page.stream_id);
  assert.equal(second.stream_seq, page.stream_seq + 1);
  assert.equal(new Set([...page.sessions, ...second.sessions].map((session) => session.session_id)).size, 1000);
  const update = store.consoleUpdates(exam.id, page.stream_seq, page.stream_id);
  assert.equal(update.resnapshot, false);
  assert.deepEqual(update.items.map((item) => item.patch), [{ connectivity: "online" }]);
  assert.equal(store.snapshot(exam.id).sessions[0].connectivity, "online");
  for (let i = 1; i <= 20; i++) {
    store.ingestEvent(sid, i, randomUUID(), "a".repeat(64), { event_type: "METRICS" });
  }
  assert.ok(store.events.length <= 5000);
  assert.equal(store.eventPartitioning, false);
  assert.equal(store.kafkaEnabled, false);
  assert.equal(store.platformView().kafka, false);
});

test("stale commands expire via worker owner; gateway max connections configured", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, `EXP-${randomUUID()}`, "e", {});
  store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  const en = [...store.enrollments.values()][0];
  const sid = store.redeemEnrollment(store.issueToken(ctx, en.id).token, "fp").session_id;
  const cmd = store.acceptCommand(ctx, sid, "WARN", "late", {});
  cmd.createdAt = Date.now() - 200_000;
  assert.equal(store.expireStaleCommands(), 1);
  assert.equal(store.commands.get(cmd.id)?.status, "expired");
  const cfg = loadConfig({ NODE_ENV: "development" } as NodeJS.ProcessEnv);
  assert.equal(cfg.GATEWAY_MAX_CONNECTIONS, 256);
  assert.ok(cfg.COMMAND_POLL_MS <= 100);
});

test("exam streams stay monotonic through expiry, gaps, and bounded catch-up", () => {
  const stream = new ConsoleStream(4, 2);
  assert.equal(stream.append("a", { op: "event" }), 1);
  assert.equal(stream.append("b", { op: "event" }), 1);
  for (let seq = 2; seq <= 5; seq++) assert.equal(stream.append("a", { op: "event" }), seq);
  assert.equal(stream.size, 4);
  assert.equal(stream.since("a", 0).resnapshot, true);
  assert.equal(stream.since("b", 0).resnapshot, true);
  assert.equal(stream.since("b", 1).resnapshot, false);
  assert.equal(stream.since("a", 6).resnapshot, true);
  assert.equal(stream.since("a", 5, "previous-instance").resnapshot, true);
  assert.equal(stream.since("a", 5, stream.id).resnapshot, false);
  assert.deepEqual(stream.since("a", 1).items.map((item) => item.stream_seq), [2, 3]);
  assert.deepEqual(stream.since("a", 3).items.map((item) => item.stream_seq), [4, 5]);
});

test("sessions added after an empty snapshot arrive as renderable upserts", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, `NEW-${randomUUID()}`, "New", {});
  const first = store.snapshot(exam.id);
  assert.equal(first.total, 0);
  const [row] = store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  assert.ok(row.id);
  const sid = store.redeemEnrollment(store.issueToken(ctx, row.id).token, "test").session_id;
  assert.deepEqual(store.deltas(exam.id, first.stream_seq), [{
    exam_id: exam.id,
    stream_seq: 1,
    op: "upsert",
    session_id: sid,
    patch: store.snapshot(exam.id).sessions[0],
  }]);
});

test("expired claim clears the owner on snapshot and the live feed", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, `CLAIM-${randomUUID()}`, "Claim", {});
  const [row] = store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  assert.ok(row.id);
  const { session_id: sessionId } = store.redeemEnrollment(store.issueToken(ctx, row.id).token, "test");
  const claim = store.claim(ctx, sessionId);
  const snapshot = store.snapshot(exam.id);
  assert.equal(snapshot.sessions[0].claim_owner, ctx.userId);
  store.expireClaims(claim.claimUntil);
  assert.equal(store.snapshot(exam.id).sessions[0].claim_owner, null);
  assert.deepEqual(store.deltas(exam.id, snapshot.stream_seq).map((item) => item.patch), [{ claim_owner: null }]);
});
