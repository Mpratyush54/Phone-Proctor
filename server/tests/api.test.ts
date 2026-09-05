import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { createHash, createHmac } from "node:crypto";
import { createApp } from "../src/app.js";
import { loadConfig } from "../src/config.js";
import { Store } from "../src/store.js";

function listen(app: ReturnType<typeof createApp>) {
  const server = http.createServer(app);
  return new Promise<{ server: http.Server; base: string }>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (!addr || typeof addr === "string") throw new Error("addr");
      resolve({ server, base: `http://127.0.0.1:${addr.port}` });
    });
  });
}

async function req(base: string, path: string, init: RequestInit & { cookies?: string } = {}) {
  const headers = new Headers(init.headers);
  if (init.cookies) headers.set("cookie", init.cookies);
  const res = await fetch(base + path, { ...init, headers, redirect: "manual" });
  const text = await res.text();
  let json: unknown = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = text;
  }
  return { status: res.status, json, headers: res.headers, raw: text };
}

function cookie(res: { headers: Headers }) {
  const raw = res.headers.get("set-cookie") || "";
  return raw.split(";")[0];
}

/** Mirror cookie-signature: 's:' + value + '.' + base64(hmac), '=' stripped. */
function signCookie(value: string, secret: string): string {
  const sig = createHmac("sha256", secret).update(value).digest("base64").replace(/=+$/, "");
  return encodeURIComponent(`s:${value}.${sig}`);
}

const TEST_SESSION_SECRET = "dev-session-secret-change-me";

function sessionCookie(raw: string): string {
  return `pp_session=${signCookie(raw, TEST_SESSION_SECRET)}`;
}

test("production refuses missing config", () => {
  assert.throws(() => loadConfig({ NODE_ENV: "production" } as NodeJS.ProcessEnv));
});

test("dev defaults bind localhost", () => {
  const cfg = loadConfig({ NODE_ENV: "development" } as NodeJS.ProcessEnv);
  assert.equal(cfg.API_HOST, "127.0.0.1");
});

test("staff oauth csrf rbac exam roster session command media finding", async () => {
  const store = new Store("pepper");
  const seeded = store.seedDev();
  const cfg = loadConfig({ NODE_ENV: "test", ORIGIN_ALLOWLIST: "http://127.0.0.1" } as NodeJS.ProcessEnv);
  const { server, base } = await listen(createApp(cfg, store));
  try {
    const sess = store.createStaffSession(seeded.orgId, seeded.userId);
    const cookies = sessionCookie(sess.raw);
    const h = { "x-csrf-token": sess.csrf, "content-type": "application/json" };

    const denied = await req(base, "/api/v1/exams", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
    assert.equal(denied.status, 401);

    const csrfFail = await req(base, "/api/v1/exams", {
      method: "POST",
      cookies,
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: "X", title: "t" }),
    });
    assert.equal(csrfFail.status, 403);

    const exam = await req(base, "/api/v1/exams", {
      method: "POST",
      cookies,
      headers: h,
      body: JSON.stringify({ code: "CS101", title: "Algo", policy: { camera: true } }),
    });
    assert.equal(exam.status, 201);
    const examId = (exam.json as { id: string }).id;

    store.openExam(store.lookupStaff(sess.raw)!, examId);
    const pol = await req(base, `/api/v1/exams/${examId}/policy`, { method: "PATCH", cookies, headers: h, body: "{}" });
    assert.equal(pol.status, 409);

    const roster = await req(base, `/api/v1/exams/${examId}/roster`, {
      method: "POST",
      cookies,
      headers: h,
      body: JSON.stringify({ rows: [{ student_external_id: "s1", display_name: "Ada" }, { student_external_id: "s1", display_name: "dup" }] }),
    });
    const results = (roster.json as { results: { ok: boolean }[] }).results;
    assert.equal(results[0].ok, true);
    assert.equal(results[1].ok, false);

    const enId = [...store.enrollments.values()][0].id;
    const tok = await req(base, `/api/v1/enrollments/${enId}/token`, { method: "POST", cookies, headers: h, body: "{}" });
    const token = (tok.json as { token: string }).token;
    const enroll = await req(base, "/api/v1/enroll", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token, fingerprint: "fp" }) });
    assert.equal((enroll.json as { session_id: string }).session_id.length > 10, true);
    const sessionId = (enroll.json as { session_id: string }).session_id;
    const replay = await req(base, "/api/v1/enroll", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token, fingerprint: "fp" }) });
    assert.equal(replay.status, 409);

    const startDenied = await req(base, `/api/v1/sessions/${sessionId}/commands`, {
      method: "POST",
      cookies,
      headers: h,
      body: JSON.stringify({ type: "EXAM_END", idempotency_key: "e1" }),
    });
    assert.equal(startDenied.status, 403);
    store.markStepUp(sess.raw);
    const ended = await req(base, `/api/v1/sessions/${sessionId}/commands`, {
      method: "POST",
      cookies,
      headers: h,
      body: JSON.stringify({ type: "EXAM_START", idempotency_key: "st1" }),
    });
    assert.equal((ended.json as { status: string }).status, "accepted");
    const again = await req(base, `/api/v1/sessions/${sessionId}/commands`, {
      method: "POST",
      cookies,
      headers: h,
      body: JSON.stringify({ type: "EXAM_START", idempotency_key: "st1" }),
    });
    assert.equal((again.json as { replay?: boolean }).replay, true);

    const payload = { event_type: "VIOLATION" };
    const hash = createHash("sha256").update(JSON.stringify(payload)).digest("hex");
    const r1 = store.ingestEvent(sessionId, 1, "b1", hash, payload);
    assert.equal(r1.acked_through, 1);
    const r2 = store.ingestEvent(sessionId, 1, "b1-dup-seq", hash, payload);
    assert.equal(r2.duplicate, true);
    assert.throws(() => store.ingestEvent(sessionId, 1, "b2", "f".repeat(64), payload));

    const snap = await req(base, `/api/v1/console/snapshot?exam_id=${examId}`, { cookies });
    assert.equal((snap.json as { exam_id: string }).exam_id, examId);

    const up = store.presignUpload(sessionId, "image/jpeg", 100, "a".repeat(64), "snapshot", { fakeUrl: true });
    store.verifyMedia(up.asset_id, false, "nope", false);
    assert.equal(store.media.get(up.asset_id)?.status, "quarantined");

    const live = await req(base, `/api/v1/sessions/${sessionId}/livekit`, {
      method: "POST",
      cookies,
      headers: h,
      body: JSON.stringify({ role: "subscribe" }),
    });
    assert.equal(live.status, 503);

    const metrics = await req(base, "/metrics");
    assert.match(metrics.raw, /phoneproctor_events_ingested_total/);
    assert.doesNotMatch(metrics.raw, /Ada|staff@example/);
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
  }
});

test("cross-tenant exam access denied", () => {
  const store = new Store();
  const a = store.seedDev();
  const orgB = store.createOrg("Other", "other");
  const userB = store.upsertUser("b@x.com", "iss", "sub-b", "B");
  store.memberships.set(`${orgB.id}:${userB.id}`, { orgId: orgB.id, userId: userB.id });
  store.roles.push({ orgId: orgB.id, userId: userB.id, role: "exam_admin" });
  const sessA = store.createStaffSession(a.orgId, a.userId);
  const ctxA = store.lookupStaff(sessA.raw)!;
  const exam = store.createExam(ctxA, "T", "t", {});
  const sessB = store.createStaffSession(orgB.id, userB.id);
  const ctxB = store.lookupStaff(sessB.raw)!;
  assert.throws(() => store.assertOrg(ctxB, exam.orgId));
});

test("oidc state replay and timeout", () => {
  const store = new Store();
  store.startOidc("s", "n", "v");
  store.consumeOidc("s", "n", "v");
  assert.throws(() => store.consumeOidc("s", "n", "v"));
  store.startOidc("s2", "n2", "v2");
  const tx = store.oidcTx.get("s2")!;
  tx.expires = Date.now() - 1;
  assert.throws(() => store.consumeOidc("s2", "n2", "v2"));
});

test("oidc callback rejects unknown state and tampered cookies", async () => {
  const store = new Store("pepper");
  store.seedDev();
  const cfg = loadConfig({ NODE_ENV: "test", ORIGIN_ALLOWLIST: "http://127.0.0.1" } as NodeJS.ProcessEnv);
  const { server, base } = await listen(createApp(cfg, store));
  try {
    const forged = `pp_oidc=${signCookie("nope", TEST_SESSION_SECRET)}`;
    const unknown = await req(base, "/api/v1/auth/callback?state=nope&code=x", { cookies: forged });
    assert.equal(unknown.status, 401);

    const mismatch = await req(base, "/api/v1/auth/callback?state=a&code=x", {
      cookies: `pp_oidc=${signCookie("b", TEST_SESSION_SECRET)}`,
    });
    assert.equal(mismatch.status, 401);

    const tampered = await req(base, "/api/v1/auth/callback?state=a&code=x", {
      cookies: "pp_oidc=s:a.invalidsignature",
    });
    assert.equal(tampered.status, 401);

    const sess = store.createStaffSession("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002");
    const forgedSession = await req(base, "/api/v1/me", { cookies: `pp_session=${sess.raw}` });
    assert.equal(forgedSession.status, 401);
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
  }
});

test("refresh replay revokes family", () => {
  const store = new Store();
  store.seedDev();
  const ctx = store.lookupStaff(store.createStaffSession([...store.orgs.keys()][0], [...store.users.keys()][0]).raw)!;
  const exam = store.createExam(ctx, "C", "c", {});
  store.importRoster(ctx, exam.id, [{ student_external_id: "1", display_name: "A" }]);
  const en = [...store.enrollments.values()][0];
  const tok = store.issueToken(ctx, en.id);
  const cred = store.redeemEnrollment(tok.token, "fp");
  store.rotateRefresh(cred.family_id, cred.refresh_token);
  assert.throws(() => store.rotateRefresh(cred.family_id, cred.refresh_token));
});
