import express, { type Express, type NextFunction, type Request, type Response } from "express";
import cookieParser from "cookie-parser";
import { randomBytes, createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ApiError, Store, type StaffContext } from "./store.js";
import type { AppConfig } from "./config.js";
import { createLogger, requestId } from "./log.js";

const OPENAPI = {
  openapi: "3.1.0",
  info: { title: "Phone-Proctor Control API", version: "1.0.0" },
  servers: [{ url: "http://127.0.0.1:8080" }],
  paths: {
    "/api/v1/auth/login": { get: { summary: "Start OIDC" } },
    "/api/v1/auth/callback": { get: { summary: "OIDC callback" } },
    "/api/v1/auth/logout": { post: { summary: "Logout" } },
    "/api/v1/auth/step-up": { post: { summary: "OIDC step-up proof" } },
    "/api/v1/permissions": { get: { summary: "Staff permissions" } },
    "/api/v1/exams": { get: { summary: "List exams" }, post: { summary: "Create exam" } },
    "/api/v1/exams/{id}/open": { post: { summary: "Open exam" } },
    "/api/v1/exams/{id}/policy": { patch: { summary: "Update policy" } },
    "/api/v1/exams/{id}/roster": { post: { summary: "Import roster" } },
    "/api/v1/exams/{id}/staff": { post: { summary: "Assign staff" } },
    "/api/v1/exams/{id}/readiness": { get: { summary: "Readiness summary" } },
    "/api/v1/exams/{id}/commands/bulk": { post: { summary: "Bulk commands" } },
    "/api/v1/enrollments/{id}/token": { post: { summary: "Issue enrollment token" } },
    "/api/v1/enroll": { post: { summary: "Redeem enrollment" } },
    "/api/v1/sessions/{id}": { get: { summary: "Student drawer" } },
    "/api/v1/sessions/{id}/commands": { post: { summary: "Dispatch command" } },
    "/api/v1/sessions/{id}/claim": { post: { summary: "Claim lease" } },
    "/api/v1/sessions/{id}/handoff": { post: { summary: "Handoff lease" } },
    "/api/v1/sessions/{id}/pairing-token": { post: { summary: "Phone pairing token" } },
    "/api/v1/sessions/{id}/phone-pair": { post: { summary: "Redeem phone pairing" } },
    "/api/v1/sessions/{id}/phone-pair/revoke": { post: { summary: "Revoke phone pairing credential" } },
    "/api/v1/console/snapshot": { get: { summary: "Console snapshot" } },
    "/api/v1/console/deltas": { get: { summary: "Console deltas after stream_seq" } },
    "/api/v1/sessions/{id}/media/uploads": { post: { summary: "Constrained media upload" } },
    "/api/v1/media/{id}/verify": { post: { summary: "Verify uploaded object" } },
    "/api/v1/sessions/{id}/thumbnail": { get: { summary: "Short-lived thumbnail" } },
    "/api/v1/sessions/{id}/livekit": { post: { summary: "LiveKit token" } },
    "/api/v1/sessions/{id}/live/start": { post: { summary: "Start live publish" } },
    "/api/v1/sessions/{id}/live/stop": { post: { summary: "Stop live when last viewer leaves" } },
    "/api/v1/sessions/{id}/legal-hold": { post: { summary: "Freeze legal hold" } },
    "/api/v1/sessions/{id}/findings": { post: { summary: "Add finding" } },
    "/api/v1/findings/{id}/reviewers": { post: { summary: "Assign two reviewers" } },
    "/api/v1/findings/{id}/appeal": { post: { summary: "Appeal finding" } },
    "/api/v1/models/{alias}": { put: { summary: "Model registry alias rollback" } },
    "/api/v1/media/inventory": { get: { summary: "Reconcile media inventory" } },
    "/api/v1/health/aggregate": { get: { summary: "Health aggregator" } },
    "/api/v1/platform/view": { get: { summary: "Tenant-blind platform view" } },
    "/health/live": { get: { summary: "Liveness" } },
    "/health/ready": { get: { summary: "Readiness" } },
    "/metrics": { get: { summary: "Prometheus metrics" } },
  },
};

declare global {
  namespace Express {
    interface Request {
      staff?: StaffContext;
      requestId?: string;
      rawSession?: string;
    }
  }
}

export function createApp(cfg: AppConfig, store: Store): Express {
  const log = createLogger("api", cfg.LOG_LEVEL);
  const app = express();
  app.disable("x-powered-by");
  app.use(express.json({ limit: "512kb" }));
  app.use(cookieParser());
  app.use((req, res, next) => {
    req.requestId = requestId();
    res.setHeader("x-request-id", req.requestId);
    const origin = req.headers.origin;
    if (origin && !cfg.origins.includes(origin)) {
      if (req.headers.upgrade === "websocket" || req.path.startsWith("/api") || req.path.startsWith("/console")) {
        return res.status(403).json({ code: "CSRF_DENIED", error: "origin" });
      }
    }
    if (origin && cfg.origins.includes(origin)) {
      res.setHeader("Access-Control-Allow-Origin", origin);
      res.setHeader("Access-Control-Allow-Credentials", "true");
    }
    next();
  });
  app.use((req, _res, next) => {
    log.info({ requestId: req.requestId, method: req.method, path: req.path }, "request");
    next();
  });

  const insecureLegacy = ["/api/exams", "/exam"];
  app.use((req, res, next) => {
    if (cfg.production && insecureLegacy.some((p) => req.path.startsWith(p))) {
      return res.status(404).json({ code: "NOT_FOUND" });
    }
    next();
  });

  function staffFrom(req: Request): StaffContext {
    const raw = req.cookies?.pp_session;
    if (!raw) throw new ApiError("AUTH_DENIED", "no session", 401);
    const ctx = store.lookupStaff(raw);
    if (!ctx) throw new ApiError("AUTH_DENIED", "invalid session", 401);
    req.rawSession = raw;
    if (["POST", "PUT", "PATCH", "DELETE"].includes(req.method)) {
      const csrf = req.headers["x-csrf-token"];
      if (!csrf || csrf !== ctx.csrf) throw new ApiError("CSRF_DENIED", "csrf", 403);
    }
    return ctx;
  }

  app.get("/health/live", (_req, res) => res.json({ status: "live", service: "api" }));
  app.get("/health/ready", (_req, res) => res.json({ status: "ready", service: "api", checks: store.health() }));
  app.get("/api/v1/openapi.json", (_req, res) => res.json(OPENAPI));

  app.get("/api/v1/auth/login", (req, res) => {
    const state = randomBytes(16).toString("hex");
    const nonce = randomBytes(16).toString("hex");
    const verifier = randomBytes(32).toString("hex");
    store.startOidc(state, nonce, verifier);
    res.cookie("pp_oidc", JSON.stringify({ state, nonce, verifier }), { httpOnly: true, sameSite: "lax", secure: cfg.production });
    const url = `${cfg.OIDC_ISSUER}/auth?client_id=${cfg.OIDC_CLIENT_ID}&redirect_uri=${encodeURIComponent(cfg.OIDC_REDIRECT_URL)}&state=${state}&nonce=${nonce}&code_challenge=dev&code_challenge_method=S256&response_type=code&scope=openid%20email`;
    res.json({ url, state });
  });

  app.get("/api/v1/auth/callback", (req, res) => {
    const cookie = req.cookies?.pp_oidc;
    const parsed = cookie ? JSON.parse(cookie) : {};
    const state = String(req.query.state || parsed.state);
    const nonce = String(req.query.nonce || parsed.nonce);
    const verifier = String(parsed.verifier || "dev-verifier");
    store.consumeOidc(state, nonce, verifier);
    const { orgId, userId } = [...store.memberships.values()][0] || store.seedDev();
    const sess = store.createStaffSession(orgId, userId);
    res.cookie("pp_session", sess.raw, { httpOnly: true, sameSite: "lax", secure: cfg.production });
    res.json({ ok: true, csrf: sess.csrf, org_id: orgId });
  });

  app.post("/api/v1/auth/dev-login", (req, res) => {
    if (cfg.production) throw new ApiError("AUTH_DENIED", "dev login disabled", 401);
    const seeded = [...store.memberships.values()][0] || store.seedDev();
    const orgId = "orgId" in seeded ? seeded.orgId : seeded.orgId;
    const userId = "userId" in seeded ? seeded.userId : seeded.userId;
    const sess = store.createStaffSession(orgId, userId);
    res.cookie("pp_session", sess.raw, { httpOnly: true, sameSite: "lax", secure: false });
    res.json({ ok: true, csrf: sess.csrf, org_id: orgId });
  });

  app.post("/api/v1/auth/logout", (req, res) => {
    const raw = req.cookies?.pp_session;
    if (raw) store.logout(raw);
    res.clearCookie("pp_session");
    res.json({ ok: true });
  });

  app.post("/api/v1/auth/step-up", (req, res) => {
    const raw = req.cookies?.pp_session;
    if (!raw) throw new ApiError("AUTH_DENIED", "no session", 401);
    store.markStepUp(raw);
    res.json({ ok: true, acr: "step-up" });
  });

  app.get("/api/v1/me", (req, res) => {
    const ctx = staffFrom(req);
    res.json({ user_id: ctx.userId, org_id: ctx.orgId, roles: ctx.roles, permissions: [...ctx.permissions], csrf: ctx.csrf });
  });

  app.get("/api/v1/permissions", (req, res) => {
    const ctx = staffFrom(req);
    res.json({ permissions: [...ctx.permissions], roles: ctx.roles });
  });

  app.post("/api/v1/exams", (req, res) => {
    const ctx = staffFrom(req);
    const exam = store.createExam(ctx, req.body.code, req.body.title, req.body.policy || { camera: true });
    res.status(201).json(exam);
  });

  app.get("/api/v1/exams", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "exam.read");
    const cursor = Number(req.query.cursor || 0);
    const items = [...store.exams.values()].filter((e) => e.orgId === ctx.orgId).slice(cursor, cursor + 50);
    res.json({ items, next_cursor: cursor + items.length });
  });

  app.get("/api/v1/exams/:id", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "exam.read");
    const exam = store.exams.get(req.params.id);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    store.assertOrg(ctx, exam.orgId);
    res.json(exam);
  });

  app.post("/api/v1/exams/:id/open", (req, res) => {
    res.json(store.openExam(staffFrom(req), req.params.id));
  });

  app.patch("/api/v1/exams/:id/policy", (req, res) => {
    res.json(store.updatePolicy(staffFrom(req), req.params.id, req.body));
  });

  app.post("/api/v1/exams/:id/roster", (req, res) => {
    const rows = Array.isArray(req.body.rows) ? req.body.rows : [];
    res.json({ results: store.importRoster(staffFrom(req), req.params.id, rows) });
  });

  app.post("/api/v1/enrollments/:id/token", (req, res) => {
    res.json(store.issueToken(staffFrom(req), req.params.id));
  });

  app.post("/api/v1/enroll", (req, res) => {
    const key = req.headers["idempotency-key"];
    res.json(store.redeemEnrollment(req.body.token, req.body.fingerprint || "fp", req.body.kind || "laptop"));
    void key;
  });

  app.post("/api/v1/sessions/:id/pairing-token", (req, res) => {
    res.json(store.issuePairingToken(staffFrom(req), req.params.id));
  });

  app.post("/api/v1/sessions/:id/phone-pair", (req, res) => {
    res.json(store.redeemPhonePairing(req.params.id, req.body.token));
  });

  app.post("/api/v1/sessions/:id/phone-pair/revoke", (req, res) => {
    res.json(store.revokePhonePairing(staffFrom(req), req.params.id, req.body.device_credential_id));
  });

  app.get("/api/v1/exams/:id/readiness", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "exam.read");
    res.json({ exam_id: req.params.id, readiness: store.readiness(req.params.id), causes: [] });
  });

  app.get("/api/v1/exams/:id/sessions", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.read");
    const cursor = Number(req.query.cursor || 0);
    const limit = Math.min(Number(req.query.limit || 200), 500);
    const snap = store.snapshot(req.params.id, { cursor, limit });
    res.json({ items: snap.sessions, next_cursor: snap.next_cursor, total: snap.total });
  });

  app.get("/api/v1/sessions/:id/events", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.read");
    const s = store.sessions.get(req.params.id);
    if (!s) throw new ApiError("NOT_FOUND", "session", 404);
    store.assertOrg(ctx, s.orgId);
    const cursor = Number(req.query.cursor || 0);
    const items = store.events.filter((e) => e.sessionId === s.id).slice(cursor, cursor + 100);
    res.json({ items, next_cursor: cursor + items.length });
  });

  app.get("/api/v1/commands/:id", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.read");
    const cmd = store.commands.get(req.params.id);
    if (!cmd) throw new ApiError("NOT_FOUND", "command", 404);
    res.json(cmd);
  });

  app.post("/api/v1/exams/:id/commands", (req, res) => {
    const ids = Array.isArray(req.body.session_ids) ? req.body.session_ids : [];
    res.json(store.bulkCommands(staffFrom(req), ids, req.body.type, req.body.idempotency_key || randomUUID()));
  });

  app.get("/api/v1/console/snapshot", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.read");
    res.json(store.snapshot(String(req.query.exam_id), {
      cursor: Number(req.query.cursor || 0),
      limit: Number(req.query.limit || 200),
    }));
  });

  app.get("/api/v1/console/deltas", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.read");
    res.json({ items: store.deltas(String(req.query.exam_id), Number(req.query.after_seq || 0)) });
  });

  app.post("/api/v1/sessions/:id/commands", (req, res) => {
    const ctx = staffFrom(req);
    const cmd = store.acceptCommand(ctx, req.params.id, req.body.type, req.body.idempotency_key, req.body.body || {});
    res.json(cmd);
  });

  app.post("/api/v1/sessions/:id/claim", (req, res) => {
    res.json(store.claim(staffFrom(req), req.params.id));
  });

  app.post("/api/v1/sessions/:id/handoff", (req, res) => {
    res.json(store.handoff(staffFrom(req), req.params.id, req.body.to_user_id));
  });

  app.get("/api/v1/sessions/:id", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.read");
    const s = store.sessions.get(req.params.id);
    if (!s) throw new ApiError("NOT_FOUND", "session", 404);
    store.assertOrg(ctx, s.orgId);
    const cmds = [...store.commands.values()].filter((c) => c.sessionId === s.id);
    const events = store.events.filter((e) => e.sessionId === s.id).slice(-50);
    res.json({ session: s, commands: cmds, events, health: { connectivity: s.connectivity, attention: s.attention } });
  });

  app.post("/api/v1/sessions/:id/media/uploads", (req, res) => {
    res.json(store.presignUpload(req.params.id, req.body.content_type, req.body.bytes, req.body.sha256, req.body.kind || "snapshot"));
  });

  app.post("/api/v1/media/:id/verify", (req, res) => {
    res.json(store.verifyMedia(req.params.id, !!req.body.head_ok, req.body.sha256, !!req.body.decodable));
  });

  app.get("/api/v1/sessions/:id/thumbnail", (req, res) => {
    res.json(store.signedThumbnail(staffFrom(req), req.params.id));
  });

  app.post("/api/v1/sessions/:id/livekit", (req, res) => {
    res.json(store.livekitToken(staffFrom(req), req.params.id, req.body.role || "subscribe"));
  });

  app.post("/api/v1/sessions/:id/live-token", (req, res) => {
    res.json(store.livekitToken(staffFrom(req), req.params.id, req.body.role || "subscribe"));
  });

  app.post("/api/v1/sessions/:id/findings", (req, res) => {
    res.json(store.addFinding(staffFrom(req), req.params.id, req.body.label, req.body.event_seq));
  });

  app.post("/api/v1/findings/:id/reviewers", (req, res) => {
    store.assignReviewers(req.params.id, req.body.a, req.body.b);
    res.json({ ok: true });
  });

  app.post("/api/v1/findings/:id/appeal", (req, res) => {
    res.json(store.appeal(req.params.id, req.body.original_reviewer_id, req.body.appeal_reviewer_id));
  });

  app.put("/api/v1/models/:alias", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "platform.ops");
    store.setAlias(req.params.alias, req.body.version, req.body.body || {});
    res.json({ alias: req.params.alias, version: req.body.version });
  });

  app.post("/api/v1/exams/:id/staff", (req, res) => {
    res.json(store.assignStaff(staffFrom(req), req.params.id, req.body.user_id, req.body.role || "invigilator"));
  });

  app.post("/api/v1/exams/:id/commands/bulk", (req, res) => {
    const ids = Array.isArray(req.body.session_ids) ? req.body.session_ids : [];
    res.json(store.bulkCommands(staffFrom(req), ids, req.body.type, req.body.idempotency_key || randomUUID()));
  });

  app.post("/api/v1/sessions/:id/legal-hold", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "exam.end");
    store.freezeLegalHold(req.params.id);
    res.json({ ok: true, hold: true });
  });

  app.get("/api/v1/media/inventory", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "platform.ops");
    res.json(store.reconcileInventory());
  });

  app.post("/api/v1/sessions/:id/live/start", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.live_view");
    res.json(store.startLive(req.params.id, ctx.userId));
  });

  app.post("/api/v1/sessions/:id/live/stop", (req, res) => {
    const ctx = staffFrom(req);
    res.json(store.stopLive(req.params.id, ctx.userId));
  });

  app.get("/api/v1/health/aggregate", (_req, res) => {
    res.json(store.pollHealth());
  });

  app.get("/api/v1/health/exams/:id", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "exam.read");
    res.json({ exam_id: req.params.id, readiness: store.readiness(req.params.id), checks: store.pollHealth() });
  });

  app.get("/api/v1/platform/health", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "platform.ops");
    res.json(store.platformView());
  });

  app.get("/api/v1/platform/view", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "platform.ops");
    res.json(store.platformView());
  });

  app.post("/api/v1/dev/ingest", (req, res) => {
    if (cfg.production) throw new ApiError("NOT_FOUND", "not found", 404);
    staffFrom(req);
    res.json(
      store.ingestEvent(
        req.body.session_id,
        Number(req.body.seq),
        req.body.batch_id || randomUUID(),
        req.body.hash || "a".repeat(64),
        req.body.payload || {},
      ),
    );
  });

  app.get("/metrics", (_req, res) => {
    res.type("text/plain").send(
      [
        "# HELP phoneproctor_events_ingested_total Events ingested",
        "# TYPE phoneproctor_events_ingested_total counter",
        `phoneproctor_events_ingested_total ${store.events.length}`,
        "# HELP phoneproctor_commands_total Commands accepted",
        "# TYPE phoneproctor_commands_total counter",
        `phoneproctor_commands_total ${store.commands.size}`,
        "# HELP phoneproctor_auth_denials_total Auth denials",
        "# TYPE phoneproctor_auth_denials_total counter",
        `phoneproctor_auth_denials_total ${store.audit.filter((a) => a.action.startsWith("deny")).length}`,
        "# HELP phoneproctor_exam_stream_rows Durable console stream rows",
        "# TYPE phoneproctor_exam_stream_rows gauge",
        `phoneproctor_exam_stream_rows ${store.examStream.length}`,
      ].join("\n"),
    );
  });

  const adminDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public");
  app.use(express.static(adminDir));

  app.use((err: unknown, req: Request, res: Response, _next: NextFunction) => {
    if (err instanceof ApiError) {
      log.warn({ requestId: req.requestId, code: err.code }, err.message);
      return res.status(err.status).json({ code: err.code, error: err.message });
    }
    log.error({ err, requestId: req.requestId }, "unhandled");
    res.status(500).json({ code: "UNAVAILABLE", error: "internal" });
  });

  return app;
}

export function hashPayload(payload: unknown) {
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex");
}
