import assert from "node:assert/strict";
import test from "node:test";
import { loadAjv, rejectUnknownMajor } from "../src/contracts.js";

test("unknown major rejected; additive optional fields ok", () => {
  assert.throws(() => rejectUnknownMajor({ v: 2 }));
  rejectUnknownMajor({ v: 1 });
  const ajv = loadAjv();
  const validate = ajv.getSchema("heartbeat");
  assert.ok(validate);
  const ok = validate({
    v: 1,
    type: "heartbeat",
    msg_id: "x",
    ts: "2026-01-01T00:00:00Z",
    payload: { rtt_ms: 1, extra_optional: true },
  });
  assert.equal(ok, true);
});
