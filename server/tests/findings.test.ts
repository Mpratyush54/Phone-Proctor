import assert from "node:assert/strict";
import test from "node:test";
import { Store } from "../src/store.js";

test("two reviewers cannot be the same actor", () => {
  const s = new Store();
  assert.throws(() => s.assignReviewers("f", "a", "a"));
});

test("appeal reviewer cannot be original and freezes evidence", () => {
  const s = new Store();
  const seeded = s.seedDev();
  s.sessions.set("sess", {
    id: "sess", orgId: seeded.orgId, examId: "e", enrollmentId: "en",
    desired: "ENDED", observed: "ENDED", controlGen: 1, connGen: 1,
    connectivity: "offline", attention: "unknown",
  });
  s.manifests.set("m", { id: "m", sessionId: "sess", frozen: false, body: {} });
  s.findings.set("f", { id: "f", sessionId: "sess", orgId: seeded.orgId, label: "phone", status: "verified" });
  s.appeal("f", "rev1", "rev2");
  assert.equal(s.manifests.get("m")?.frozen, true);
  assert.throws(() => s.appeal("f", "rev1", "rev1"));
});

test("model alias rollback is one write", () => {
  const s = new Store();
  s.setAlias("live", "1", { head: "rules" });
  s.setAlias("live", "0", { head: "rules" });
  assert.equal(s.modelRegistry.get("live")?.version, "0");
});
