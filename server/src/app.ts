import express, { type Express, type NextFunction, type Request, type Response } from "express";
import cookieParser from "cookie-parser";
import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ApiError, Store, type StaffContext } from "./store.js";
import type { AppConfig } from "./config.js";
import { beginOidc, completeOidc } from "./oidc.js";
import { objectStoreConfigured, presignUrl, signThumbnail, verifyThumbnail } from "./media.js";
import { createLogger, requestId } from "./log.js";

const OPENAPI = {
  openapi: "3.1.0",
  info: { title: "Phone-Proctor Control API", version: "1.0.0" },
  servers: [{ url: "http://127.0.0.1:8080" }],
  paths: {
    "/api/v1/auth/login": { get: { summary: "Start OIDC" } },
    "/api/v1/auth/callback": { get: { summary: "OIDC callback" } },
    "/api/v1/auth/logout": { post: { summary: "Logout" } },
    "/api/v1/auth/step-up": { post: { summary: "Start OIDC step-up (returns login URL)" } },
    "/api/v1/auth/step-up/callback": { get: { summary: "Complete OIDC step-up" } },
    "/api/v1/me": { get: { summary: "Current staff" } },
    "/api/v1/exams": { get: { summary: "List exams" }, post: { summary: "Create exam" } },
    "/api/v1/exams/{id}/open": { post: { summary: "Open exam" } },
    "/api/v1/exams/{id}/policy": { patch: { summary: "Update policy" } },
    "/api/v1/exams/{id}/roster": { post: { summary: "Import roster" } },
    "/api/v1/exams/{id}/staff": { post: { summary: "Assign staff" } },
    "/api/v1/banks": { get: { summary: "List question banks" }, post: { summary: "Create bank" } },
    "/api/v1/banks/{id}/groups": { post: { summary: "Add question group" } },
    "/api/v1/groups/{id}/variants": { post: { summary: "Add question variant" } },
    "/api/v1/variants/{id}/deprecate": { post: { summary: "Deprecate variant" } },
    "/api/v1/banks/{id}/publish": { post: { summary: "Publish content version" } },
    "/api/v1/exams/{id}/content": { patch: { summary: "Bind content version" } },
    "/api/v1/enrollments/{id}/candidate-code": { post: { summary: "Issue candidate login code" } },
    "/api/v1/enrollments/{id}/candidate-codes": { get: { summary: "Candidate code status" } },
    "/api/v1/sessions/{id}/answers": { get: { summary: "Session answers (staff)" } },
    "/api/v1/candidate/login": { post: { summary: "Candidate login with code" } },
    "/api/v1/candidate/logout": { post: { summary: "Candidate logout" } },
    "/api/v1/candidate/next-item": { get: { summary: "Next exam item (one by one)" } },
    "/api/v1/candidate/answer": { post: { summary: "Submit answer" } },
    "/api/v1/candidate/status": { get: { summary: "Candidate progress" } },
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
  app.use(cookieParser(cfg.SESSION_SECRET));
  app.use((req, res, next) => {
    req.requestId = requestId();
    res.setHeader("x-request-id", req.requestId);
    const origin = req.headers.origin;
    if (origin) res.setHeader("Vary", "Origin");
    if (req.method === "OPTIONS") {
      if (origin && cfg.origins.includes(origin)) {
        res.setHeader("Access-Control-Allow-Origin", origin);
        res.setHeader("Access-Control-Allow-Credentials", "true");
        res.setHeader("Access-Control-Allow-Methods", "GET,POST,PATCH,PUT,DELETE,OPTIONS");
        res.setHeader("Access-Control-Allow-Headers", "content-type,x-csrf-token,x-request-id");
        res.setHeader("Access-Control-Max-Age", "600");
      }
      return res.status(204).end();
    }
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

  /** Verified (signed) cookie value, or null when missing/tampered. */
  function signedCookie(req: Request, name: string): string | null {
    const value: unknown = (req.signedCookies as Record<string, unknown> | undefined)?.[name];
    return typeof value === "string" && value.length > 0 ? value : null;
  }

  function sessionCookie(res: Response, name: string, value: string, maxAgeMs?: number) {
    res.cookie(name, value, {
      httpOnly: true,
      sameSite: "lax",
      secure: cfg.production,
      signed: true,
      path: "/",
      ...(maxAgeMs !== undefined ? { maxAge: maxAgeMs } : {}),
    });
  }

  /** Resolve the staff member for an OIDC identity. No silent demo provisioning. */
  function resolveStaff(issuer: string, sub: string, email?: string, name?: string): { orgId: string; userId: string } {
    const user = store.findUser(issuer, sub);
    if (!user) {
      if (
        cfg.BOOTSTRAP_ADMIN_EMAIL &&
        email &&
        email.toLowerCase() === cfg.BOOTSTRAP_ADMIN_EMAIL.toLowerCase()
      ) {
        return store.bootstrapAdmin(email, name || email, issuer, sub);
      }
      throw new ApiError("AUTH_DENIED", "no account for this identity", 403);
    }
    if (email) {
      try {
        store.syncUserProfile(user.id, email, name || user.name);
      } catch {
        throw new ApiError("AUTH_DENIED", "identity conflict", 403);
      }
    }
    const memberships = store.membershipsFor(user.id);
    if (memberships.length === 0) throw new ApiError("AUTH_DENIED", "no organization membership", 403);
    if (memberships.length > 1) {
      throw new ApiError(
        "ORG_SELECTION_REQUIRED",
        "multiple memberships",
        409,
      );
    }
    return { orgId: memberships[0].orgId, userId: user.id };
  }

  function staffFrom(req: Request): StaffContext {
    const raw = signedCookie(req, "pp_session");
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

  app.get("/api/v1/auth/login", async (req, res, next) => {
    try {
      const { state, url } = await beginOidc(cfg, store);
      sessionCookie(res, "pp_oidc", state, 5 * 60_000);
      res.json({ url, state });
    } catch (err) {
      next(err);
    }
  });

  app.get("/api/v1/auth/callback", async (req, res, next) => {
    try {
      const cookieState = signedCookie(req, "pp_oidc");
      const state = String(req.query.state || "");
      const code = String(req.query.code || "");
      if (req.query.error) {
        throw new ApiError("AUTH_DENIED", `provider refused: ${String(req.query.error_description || req.query.error)}`, 401);
      }
      if (!cookieState || !state || cookieState !== state) {
        throw new ApiError("AUTH_DENIED", "state mismatch", 401);
      }
      if (!code) throw new ApiError("AUTH_DENIED", "missing code", 401);
      const claims = await completeOidc(cfg, store, state, code);
      const { orgId, userId } = resolveStaff(claims.issuer, claims.sub, claims.email, claims.name);
      const sess = store.createStaffSession(orgId, userId);
      res.clearCookie("pp_oidc", { path: "/" });
      sessionCookie(res, "pp_session", sess.raw);
      res.json({ ok: true, csrf: sess.csrf, org_id: orgId });
    } catch (err) {
      next(err);
    }
  });

  app.post("/api/v1/auth/dev-login", (req, res) => {
    if (!cfg.allowDevLogin) throw new ApiError("AUTH_DENIED", "dev login disabled", 401);
    const first = [...store.memberships.values()][0];
    if (!first) throw new ApiError("AUTH_DENIED", "no staff users provisioned", 503);
    const sess = store.createStaffSession(first.orgId, first.userId);
    sessionCookie(res, "pp_session", sess.raw);
    res.json({ ok: true, csrf: sess.csrf, org_id: first.orgId });
  });

  app.post("/api/v1/auth/logout", (req, res) => {
    const raw = signedCookie(req, "pp_session");
    if (raw) store.logout(raw);
    res.clearCookie("pp_session", { path: "/" });
    res.json({ ok: true });
  });

  app.post("/api/v1/auth/step-up", async (req, res, next) => {
    try {
      staffFrom(req);
      const { state, url } = await beginOidc(cfg, store, {
        prompt: "login",
        acrValues: cfg.OIDC_ACR_VALUES,
        maxAge: cfg.OIDC_MAX_AGE ?? 0,
      });
      sessionCookie(res, "pp_stepup", state, 5 * 60_000);
      res.json({ url, state });
    } catch (err) {
      next(err);
    }
  });

  app.get("/api/v1/auth/step-up/callback", async (req, res, next) => {
    try {
      const raw = signedCookie(req, "pp_session");
      if (!raw) throw new ApiError("AUTH_DENIED", "no session", 401);
      const cookieState = signedCookie(req, "pp_stepup");
      const state = String(req.query.state || "");
      const code = String(req.query.code || "");
      if (req.query.error) {
        throw new ApiError("AUTH_DENIED", `provider refused: ${String(req.query.error_description || req.query.error)}`, 401);
      }
      if (!cookieState || !state || cookieState !== state) {
        throw new ApiError("AUTH_DENIED", "state mismatch", 401);
      }
      if (!code) throw new ApiError("AUTH_DENIED", "missing code", 401);
      await completeOidc(cfg, store, state, code, {
        requireFreshAuthSeconds: 5 * 60,
        requireAcr: cfg.OIDC_ACR_VALUES,
      });
      store.markStepUp(raw);
      res.clearCookie("pp_stepup", { path: "/" });
      res.json({ ok: true, acr: cfg.OIDC_ACR_VALUES || "step-up" });
    } catch (err) {
      next(err);
    }
  });

  app.get("/api/v1/me", (req, res) => {
    const ctx = staffFrom(req);
    res.json({ user_id: ctx.userId, org_id: ctx.orgId, roles: ctx.roles, permissions: [...ctx.permissions], csrf: ctx.csrf });
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

  app.get("/api/v1/console/snapshot", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "session.read");
    res.json(store.snapshot(String(req.query.exam_id)));
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
    res.json(store.presignUpload(
      req.params.id, req.body.content_type, req.body.bytes, req.body.sha256, req.body.kind || "snapshot",
      { fakeUrl: cfg.mediaFake },
    ));
  });

  app.post("/api/v1/media/:id/verify", (req, res) => {
    res.json(store.verifyMedia(req.params.id, !!req.body.head_ok, req.body.sha256, !!req.body.decodable));
  });

  app.get("/api/v1/sessions/:id/thumbnail", (req, res) => {
    const ctx = staffFrom(req);
    const result = store.signedThumbnail(ctx, req.params.id);
    if (!result.available) return res.json(result);
    const expiresAt = Date.now() + result.expires_s * 1000;
    const sig = signThumbnail(cfg.SESSION_SECRET, result.asset_id, expiresAt);
    res.json({
      ...result,
      url: `/api/v1/media/${result.asset_id}/thumb?exp=${expiresAt}&sig=${sig}`,
    });
  });

  app.get("/api/v1/media/:id/thumb", (req, res, next) => {
    try {
      const ctx = staffFrom(req);
      const asset = store.media.get(req.params.id);
      if (!asset) throw new ApiError("NOT_FOUND", "asset", 404);
      store.assertOrg(ctx, asset.orgId);
      const exp = Number(req.query.exp || 0);
      const sig = String(req.query.sig || "");
      if (!verifyThumbnail(cfg.SESSION_SECRET, asset.id, exp, sig)) {
        throw new ApiError("AUTH_DENIED", "thumbnail token invalid or expired", 401);
      }
      if (asset.status !== "verified") throw new ApiError("NOT_FOUND", "asset not available", 404);
      store.recordAudit({ orgId: asset.orgId, actorId: ctx.userId, action: "media.read", payload: { assetId: asset.id } });
      const osc = {
        endpoint: process.env.OBJECT_STORE_ENDPOINT || "http://127.0.0.1:9000",
        bucket: process.env.OBJECT_STORE_BUCKET || "phone-proctor",
        region: process.env.OBJECT_STORE_REGION || "us-east-1",
        accessKey: process.env.OBJECT_STORE_ACCESS_KEY,
        secretKey: process.env.OBJECT_STORE_SECRET_KEY,
      };
      if (!objectStoreConfigured(osc)) throw new ApiError("MEDIA_UNCONFIGURED", "object store not configured", 503);
      res.redirect(302, presignUrl(osc, "GET", asset.key, { expiresS: 60 }));
    } catch (err) {
      next(err);
    }
  });

  app.post("/api/v1/sessions/:id/livekit", async (req, res, next) => {
    try {
      res.json(await store.livekitToken(staffFrom(req), req.params.id, req.body.role || "subscribe", { fake: cfg.mediaFake }));
    } catch (err) {
      next(err);
    }
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

  /* ---------------- exam content (staff) ---------------- */

  app.post("/api/v1/banks", (req, res) => {
    res.json(store.createBank(staffFrom(req), req.body.name));
  });

  app.get("/api/v1/banks", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "exam.read");
    res.json({
      items: [...store.banks.values()].filter((b) => b.orgId === ctx.orgId).map((b) => ({
        ...b,
        groups: [...store.qgroups.values()].filter((g) => g.bankId === b.id).sort((x, y) => x.position - y.position).map((g) => ({
          ...g,
          variants: [...store.variants.values()].filter((v) => v.groupId === g.id).map((v) => ({
            id: v.id, position: v.position, stem: v.stem, qtype: v.qtype,
            per_question_s: v.perQuestionS ?? null, deprecated: !!v.deprecated,
            content_version_id: v.contentVersionId ?? null,
            options: [...store.qoptions.values()].filter((o) => o.variantId === v.id)
              .sort((x, y) => x.position - y.position).map((o) => ({ id: o.id, label: o.label })),
          })),
        })),
        versions: [...store.contentVersions.values()].filter((v) => v.bankId === b.id).sort((x, y) => x.version - y.version),
      })),
    });
  });

  app.post("/api/v1/banks/:id/groups", (req, res) => {
    res.json(store.createGroup(staffFrom(req), req.params.id, {
      title: req.body.title,
      position: req.body.position,
      marks: req.body.marks,
      negativeMarks: req.body.negative_marks,
      rubric: req.body.rubric,
    }));
  });

  app.post("/api/v1/groups/:id/variants", (req, res) => {
    res.json(store.createVariant(staffFrom(req), req.params.id, {
      stem: req.body.stem,
      qtype: req.body.qtype,
      perQuestionS: req.body.per_question_s,
      position: req.body.position,
      options: req.body.options || [],
    }));
  });

  app.post("/api/v1/variants/:id/deprecate", (req, res) => {
    res.json(store.deprecateVariant(staffFrom(req), req.params.id));
  });

  app.post("/api/v1/banks/:id/publish", (req, res) => {
    res.json(store.publishBank(staffFrom(req), req.params.id));
  });

  app.patch("/api/v1/exams/:id/content", (req, res) => {
    res.json(store.bindExamContent(staffFrom(req), req.params.id, {
      contentVersionId: req.body.content_version_id,
      allowBackNavigation: req.body.allow_back_navigation,
      durationS: req.body.duration_s,
    }));
  });

  app.post("/api/v1/enrollments/:id/candidate-code", (req, res) => {
    res.json(store.issueCandidateCode(staffFrom(req), req.params.id));
  });

  app.get("/api/v1/enrollments/:id/candidate-codes", (req, res) => {
    res.json({ items: store.candidateCodeStatus(staffFrom(req), req.params.id) });
  });

  app.get("/api/v1/sessions/:id/answers", (req, res) => {
    res.json({ items: store.sessionAnswers(staffFrom(req), req.params.id) });
  });

  /* ---------------- candidate exam (pp_candidate grant cookie) ---------------- */

  function candidateFrom(req: Request): { sessionId: string; enrollmentId: string; csrf: string } {
    const raw = signedCookie(req, "pp_candidate");
    if (!raw) throw new ApiError("AUTH_DENIED", "no candidate session", 401);
    const grant = store.candidateFromGrant(raw);
    if (["POST", "PUT", "PATCH", "DELETE"].includes(req.method)) {
      const csrf = req.headers["x-csrf-token"];
      if (!csrf || csrf !== grant.csrf) throw new ApiError("CSRF_DENIED", "csrf", 403);
    }
    return grant;
  }

  app.post("/api/v1/candidate/login", (req, res, next) => {
    try {
      const code = String(req.body.code || "");
      if (!code) throw new ApiError("VALIDATION", "code required", 400);
      const result = store.redeemCandidateCode(code);
      sessionCookie(res, "pp_candidate", result.grant);
      res.json({ csrf: result.csrf, session_id: result.session_id, exam: result.exam });
    } catch (err) {
      next(err);
    }
  });

  app.post("/api/v1/candidate/logout", (req, res) => {
    res.clearCookie("pp_candidate", { path: "/" });
    res.json({ ok: true });
  });

  app.get("/api/v1/candidate/next-item", (req, res, next) => {
    try {
      res.json(store.nextItem(candidateFrom(req).sessionId));
    } catch (err) {
      next(err);
    }
  });

  app.post("/api/v1/candidate/answer", (req, res, next) => {
    try {
      const grant = candidateFrom(req);
      res.json(store.submitAnswer(
        grant.sessionId,
        String(req.body.variant_id || ""),
        Array.isArray(req.body.option_ids) ? req.body.option_ids.map(String) : [],
        String(req.body.text_answer || ""),
      ));
    } catch (err) {
      next(err);
    }
  });

  app.get("/api/v1/candidate/status", (req, res, next) => {
    try {
      res.json(store.candidateStatus(candidateFrom(req).sessionId));
    } catch (err) {
      next(err);
    }
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

  app.get("/api/v1/platform/view", (req, res) => {
    const ctx = staffFrom(req);
    store.require(ctx, "platform.ops");
    res.json(store.platformView());
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
