import { randomUUID } from "node:crypto";
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
  const exam = store.createExam(ctx, `G-${randomUUID()}`, "g", {});
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
    assert.equal(store.sessions.get(cred.session_id)?.connectivity, "online");
    const payload = { event_type: "METRICS", gaze_h: 0.1 };
    const hash = "a".repeat(64);
    ws.send(JSON.stringify({ v: 1, type: "event", seq_no: 2, batch_id: randomUUID(), payload_hash: hash, payload }));
    const gap = await recv();
    assert.equal(gap.type, "ack");
    assert.equal((gap.payload as { acked_through: number }).acked_through, 0);
    ws.send(JSON.stringify({ v: 1, type: "event", seq_no: 1, batch_id: randomUUID(), payload_hash: hash, payload }));
    const ack = await recv();
    assert.equal(ack.type, "ack");
    assert.equal((ack.payload as { acked_through: number }).acked_through, 2);
    ws.send(JSON.stringify({ v: 1, type: "event", seq_no: 1, batch_id: "b1-dup", payload_hash: hash, payload }));
    const ack2 = await recv();
    assert.equal(ack2.type, "ack");
    const closed = new Promise<void>((resolve) => ws.once("close", () => resolve()));
    ws.close();
    await closed;
    assert.equal(store.sessions.get(cred.session_id)?.connectivity, "offline");
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
  const exam = store.createExam(ctx, `T-${randomUUID()}`, "t", {});
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
    assert.equal((cmd.payload as { command_type: string }).command_type, "WARN");
    b.ws.close();
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
  }
});


test("desktop camera precheck blocks start and can be retried before the exam", async () => {
  const store = new Store();
  const seeded = store.seedDev();
  const ctx = store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
  const exam = store.createExam(ctx, `DESKTOP-${randomUUID()}`, "Camera exam", { camera: true });
  store.openExam(ctx, exam.id);
  const [enrollment] = store.importRoster(ctx, exam.id, [{ student_external_id: "one", display_name: "Candidate" }]);
  const credential = store.redeemEnrollment(store.issueToken(ctx, enrollment.id!).token, "desktop", "laptop", true);
  assert.equal(credential.camera_required, true);
  assert.equal(store.sessions.get(credential.session_id)?.observed, "PRECHECK");
  const server = startGateway(store, { listen: false });
  const url = await waitListening(server);
  const ws = new WebSocket(url);
  try {
    await new Promise<void>((resolve) => ws.once("open", resolve));
    const send = (type: string, payload: unknown) => new Promise<{ type: string; payload?: { observed_lifecycle_state?: string } }>((resolve) => {
      ws.once("message", (message) => resolve(JSON.parse(String(message))));
      ws.send(JSON.stringify({ v: 1, type, payload }));
    });
    assert.equal((await send("hello", {})).type, "hello-ok");
    const blocked = await send("resume", { ...credential, camera_ready: false });
    assert.equal(blocked.payload?.observed_lifecycle_state, "BLOCKED");
    assert.throws(() => store.acceptCommand(ctx, credential.session_id, "EXAM_START", "blocked", {}), /lifecycle/);
    const ready = await send("heartbeat", { camera_ready: true });
    assert.equal(ready.payload?.observed_lifecycle_state, "READY");
    assert.equal(store.acceptCommand(ctx, credential.session_id, "EXAM_START", "start", {}).status, "accepted");
    // A later readiness report can't overwrite an exam with a pending start.
    store.applyDesktopPrecheck(credential.session_id, false);
    assert.equal(store.sessions.get(credential.session_id)?.desired, "IN_EXAM");
  } finally {
    const closed = new Promise<void>((resolve) => ws.once("close", () => resolve()));
    ws.close();
    await closed;
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

test("exam website reaches the desktop and is locked after enrollment", () => {
  const store = new Store();
  const seeded = store.seedDev();
  const ctx = store.lookupStaff(store.createStaffSession(seeded.orgId, seeded.userId).raw)!;
  const exam = store.createExam(ctx, `SITE-${randomUUID()}`, "Website exam", { camera: true });
  store.openExam(ctx, exam.id);
  assert.throws(() => store.saveExamLink(ctx, exam.id, "http://exam.example/"), /HTTPS/);
  assert.throws(() => store.saveExamLink(ctx, exam.id, "https://credentials@exam.example/"), /HTTPS/);
  assert.equal(store.saveExamLink(ctx, exam.id, "https://exam.example/test").exam_url, "https://exam.example/test");
  const [student] = store.importRoster(ctx, exam.id, [{ student_external_id: "one", display_name: "Candidate" }]);
  const credential = store.redeemEnrollment(store.issueToken(ctx, student.id!).token, "desktop", "laptop", true);
  assert.equal(credential.exam_url, "https://exam.example/test");
  assert.equal(credential.camera_required, true);
  assert.equal(store.examDetails(ctx, exam.id).exam_url_editable, false);
  assert.throws(() => store.saveExamLink(ctx, exam.id, null), /locked/);
});
