import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { WebSocket } from "ws";
import { startGateway } from "../src/gateway.js";
import { Store } from "../src/store.js";

function waitListening(server: http.Server) {
  return new Promise<string>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (!addr || typeof addr === "string") throw new Error("addr");
      resolve(`ws://127.0.0.1:${addr.port}`);
    });
  });
}

test("C2 hello resume heartbeat and C4 ack without duplicate", async () => {
  const store = new Store();
  const seeded = store.seedDev();
  const ctx = store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
  const exam = store.createExam(ctx, "G", "g", {});
  store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  const en = [...store.enrollments.values()][0];
  const tok = store.issueToken(ctx, en.id);
  const cred = store.redeemEnrollment(tok.token, "fp");
  process.env.GATEWAY_PORT = "0";
  const server = startGateway(store, { listen: false });
  const url = await waitListening(server);
  try {
    const ws = new WebSocket(url);
    await new Promise((r) => ws.once("open", r));
    const recv = () => new Promise<Record<string, unknown>>((resolve) => ws.once("message", (d) => resolve(JSON.parse(String(d)))));
    ws.send(JSON.stringify({ v: 1, type: "hello", msg_id: "1", ts: "2026-01-01T00:00:00Z", payload: { device_credential_id: cred.device_credential_id, session_id: cred.session_id } }));
    assert.equal((await recv()).type, "hello-ok");
    ws.send(JSON.stringify({ v: 1, type: "resume", msg_id: "2", ts: "2026-01-01T00:00:00Z", payload: { device_credential_id: cred.device_credential_id, session_id: cred.session_id, last_acked_seq: 0 } }));
    assert.equal((await recv()).type, "resumed");
    const payload = { event_type: "METRICS", gaze_h: 0.1 };
    const hash = "a".repeat(64);
    ws.send(JSON.stringify({ v: 1, type: "event", seq_no: 1, batch_id: "b1", payload_hash: hash, payload }));
    const ack = await recv();
    assert.equal(ack.type, "ack");
    ws.send(JSON.stringify({ v: 1, type: "event", seq_no: 1, batch_id: "b1-dup", payload_hash: hash, payload }));
    const ack2 = await recv();
    assert.equal(ack2.type, "ack");
    ws.close();
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
  }
});

test("unknown major nacks", async () => {
  const store = new Store();
  const server = startGateway(store, { listen: false });
  const url = await waitListening(server);
  try {
    const ws = new WebSocket(url);
    await new Promise((r) => ws.once("open", r));
    const recv = () => new Promise<Record<string, unknown>>((resolve) => ws.once("message", (d) => resolve(JSON.parse(String(d)))));
    ws.send(JSON.stringify({ v: 2, type: "hello" }));
    const nack = await recv();
    assert.equal(nack.type, "nack");
    ws.close();
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
  }
});

test("connection takeover closes previous socket; pending command is delivered", async () => {
  const store = new Store();
  const seeded = store.seedDev();
  const ctx = store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
  const exam = store.createExam(ctx, "T", "t", {});
  store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  const en = [...store.enrollments.values()][0];
  const cred = store.redeemEnrollment(store.issueToken(ctx, en.id).token, "fp");
  store.acceptCommand(ctx, cred.session_id, "WARN", "k1", {});
  const server = startGateway(store, { listen: false });
  const url = await waitListening(server);
  try {
    async function connect() {
      const ws = new WebSocket(url);
      await new Promise((r) => ws.once("open", r));
      const recv = () => new Promise<Record<string, unknown>>((resolve) => ws.once("message", (d) => resolve(JSON.parse(String(d)))));
      ws.send(JSON.stringify({ v: 1, type: "hello", payload: {} }));
      await recv();
      ws.send(JSON.stringify({ v: 1, type: "resume", payload: { device_credential_id: cred.device_credential_id, session_id: cred.session_id } }));
      await recv();
      return { ws };
    }
    const a = await connect();
    const closed = new Promise<number>((resolve) => a.ws.once("close", (code) => resolve(code)));
    const b = await connect();
    assert.equal(await closed, 4409);
    const cmd = await Promise.race([
      new Promise<Record<string, unknown>>((resolve) => b.ws.once("message", (d) => resolve(JSON.parse(String(d))))),
      new Promise<Record<string, unknown>>((resolve) => setTimeout(() => resolve({ type: "timeout" }), 800)),
    ]);
    assert.equal(cmd.type, "command");
    b.ws.close();
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
  }
});

