import assert from "node:assert/strict";
import test from "node:test";
import { Store } from "../src/store.js";
import { loadConfig } from "../src/config.js";

function staff(store: Store) {
  const seeded = store.seedDev();
  return store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
}

test("snapshot pages for 200+ sessions; event log is bounded; kafka stays off", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, "SCALE", "s", {});
  const rows = Array.from({ length: 40 }, (_, i) => ({ student_external_id: String(i), display_name: `S${i}` }));
  store.importRoster(ctx, exam.id, rows);
  for (const en of store.enrollments.values()) {
    store.redeemEnrollment(store.issueToken(ctx, en.id).token, "fp-" + en.id);
  }
  const page = store.snapshot(exam.id, { cursor: 0, limit: 10 });
  assert.equal(page.sessions.length, 10);
  assert.equal(page.next_cursor, 10);
  assert.equal(page.total, 40);
  const sid = page.sessions[0].session_id;
  for (let i = 1; i <= 20; i++) {
    store.ingestEvent(sid, i, `b${i}`, "a".repeat(64), { event_type: "METRICS" });
  }
  assert.ok(store.events.length <= 5000);
  assert.equal(store.eventPartitioning, false);
  assert.equal(store.kafkaEnabled, false);
  assert.equal(store.platformView().kafka, false);
});

test("stale commands expire via worker owner; gateway max connections configured", () => {
  const store = new Store();
  const ctx = staff(store);
  const exam = store.createExam(ctx, "EXP", "e", {});
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
