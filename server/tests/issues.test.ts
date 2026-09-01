import assert from "node:assert/strict";
import test from "node:test";
import { Store } from "../src/store.js";

function staff(store: Store) {
  const seeded = store.seedDev();
  return store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
}

test("B6b pairing cannot register agent; replay denied", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, "P", "p", {});
  store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  const en = [...store.enrollments.values()][0];
  const tok = store.issueToken(ctx, en.id);
  const cred = store.redeemEnrollment(tok.token, "fp");
  const pair = store.issuePairingToken(ctx, cred.session_id);
  assert.equal(pair.can_register_agent, false);
  const phone = store.redeemPhonePairing(cred.session_id, pair.token);
  assert.equal(phone.kind, "phone");
  assert.equal(phone.can_register_agent, false);
  assert.throws(() => store.redeemPhonePairing(cred.session_id, pair.token));
});

test("D4b bulk commands partial failure; G2 redis down degrades fanout", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, "B", "b", {});
  store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }, { student_external_id: "2", display_name: "B" }]);
  const ids = [];
  for (const en of store.enrollments.values()) {
    const t = store.issueToken(ctx, en.id);
    ids.push(store.redeemEnrollment(t.token, "fp").session_id);
  }
  const bulk = store.bulkCommands(ctx, [...ids, "missing"], "WARN", "bulk-1");
  assert.equal(bulk.all_ok, false);
  assert.equal(bulk.results.filter((r) => r.ok).length, 2);
  store.redisDown = true;
  const h = store.pollHealth();
  assert.equal(h.fanout, "degraded");
  assert.equal(h.source, "postgres");
  assert.equal(store.platformView().kafka, false);
  assert.equal(store.eventPartitioning, false);
});

test("E10 legal hold and STOP_LIVE; F9 shadow does not throw", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, "M", "m", {});
  store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  const en = [...store.enrollments.values()][0];
  const sid = store.redeemEnrollment(store.issueToken(ctx, en.id).token, "fp").session_id;
  store.freezeLegalHold(sid);
  assert.equal(store.retainOrDiscard(sid).action, "hold");
  store.startLive(sid, ctx.userId);
  assert.equal(store.stopLive(sid, ctx.userId).stopped, true);
  const r = store.ingestEvent(sid, 1, "b", "a".repeat(64), { event_type: "METRICS", gaze_h: 0.9 });
  assert.equal(r.duplicate, false);
  assert.ok(store.shadows.length >= 1);
});
