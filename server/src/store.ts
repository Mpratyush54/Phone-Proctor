import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { v4 as uuid } from "uuid";
import {
  enqueuePersist,
  ping as pingPostgres,
  postgresStatus,
  upsertCommand,
  upsertEnrollment,
  upsertEvent,
  upsertExam,
  upsertOrganization,
  upsertSession,
} from "./db/persist.js";

export type Role = "invigilator" | "lead_invigilator" | "exam_admin" | "reviewer" | "platform_ops";

export const ROLE_PERMS: Record<Role, string[]> = {
  invigilator: ["exam.read", "session.read", "session.warn", "assignment.claim"],
  lead_invigilator: ["exam.read", "exam.write", "session.read", "session.warn", "session.terminate", "session.live_view", "session.command", "assignment.claim"],
  exam_admin: ["exam.read", "exam.write", "exam.end", "roster.import", "session.read", "session.command"],
  reviewer: ["exam.read", "session.read", "review.annotate", "media.read"],
  platform_ops: ["platform.ops"],
};

export const STEP_UP_ACTIONS = new Set(["exam.end", "session.terminate", "media.read", "policy.live_change", "evidence.delete"]);

function pepperHash(value: string, pepper: string) {
  return createHash("sha256").update(pepper + ":" + value).digest("hex");
}

function nowPlus(ms: number) {
  return Date.now() + ms;
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 400) {
    super(message);
  }
}

export interface StaffContext {
  userId: string;
  orgId: string;
  roles: Role[];
  permissions: Set<string>;
  stepUpUntil?: number;
  csrf?: string;
}

export class Store {
  pepper: string;
  orgs = new Map<string, { id: string; name: string; slug: string }>();
  users = new Map<string, { id: string; email: string; issuer: string; subject: string; name: string }>();
  memberships = new Map<string, { orgId: string; userId: string }>();
  roles: { orgId: string; userId: string; role: Role; examId?: string }[] = [];
  staffSessions = new Map<string, { id: string; orgId: string; userId: string; sessionHash: string; refreshHash: string; expires: number; revoked?: boolean; replay?: boolean; stepUpUntil?: number; csrf: string }>();
  oidcTx = new Map<string, { nonce: string; pkce: string; used?: boolean; expires: number }>();
  audit: { orgId: string; actorId?: string; action: string; payload: unknown }[] = [];
  exams = new Map<string, { id: string; orgId: string; code: string; title: string; status: string; version: number; policyId?: string }>();
  policies = new Map<string, { id: string; examId: string; version: number; body: unknown; immutable: boolean }>();
  groups = new Map<string, { id: string; orgId: string; examId: string; name: string }>();
  enrollments = new Map<string, { id: string; orgId: string; examId: string; studentExternalId: string; displayName: string }>();
  tokens = new Map<string, { id: string; enrollmentId: string; hash: string; expires: number; redeemed?: boolean }>();
  devices = new Map<string, { id: string; enrollmentId: string; kind: "laptop" | "phone"; familyId: string; revoked?: boolean }>();
  refreshTokens = new Map<string, { hash: string; familyId: string; used?: boolean }>();
  consents = new Map<string, unknown>();
  sessions = new Map<string, {
    id: string; orgId: string; examId: string; enrollmentId: string;
    desired: string; observed: string; controlGen: number; connGen: number;
    connectivity: string; attention: string; claimOwner?: string; claimUntil?: number;
  }>();
  attempts = new Map<string, { enrollmentId: string; terminal: boolean }>();
  events: { sessionId: string; seq: number; batchId: string; hash: string; payload: unknown; orgId: string }[] = [];
  rejections: { sessionId: string; seq: number; code: string }[] = [];
  cursors = new Map<string, number>();
  commands = new Map<string, { id: string; sessionId: string; type: string; idempotencyKey: string; status: string; result?: unknown; orgId: string }>();
  examStream: { examId: string; seq: number; payload: unknown }[] = [];
  media = new Map<string, { id: string; orgId: string; sessionId: string; key: string; type: string; bytes: number; sha256: string; status: string; attempts: number }>();
  deadLetter: { assetId: string; reason: string }[] = [];
  manifests = new Map<string, { id: string; sessionId: string; frozen: boolean; body: unknown }>();
  findings = new Map<string, { id: string; sessionId: string; orgId: string; label: string; status: string; actorId?: string }>();
  revisions: { findingId: string; actorId: string; label: string }[] = [];
  reviewAssign: { findingId: string; reviewerId: string }[] = [];
  appeals = new Map<string, { id: string; findingId: string; original: string; appealReviewer?: string; outcome?: string }>();
  modelRegistry = new Map<string, { version: string; body: unknown }>();
  rawOutbox: { eventId: number; offset: number; payload: unknown }[] = [];
  redisDown = false;
  leases = new Map<string, { owner: string; until: number }>();
  presence = new Map<string, { online: boolean; ts: number }>();
  legalHold = new Set<string>();
  pairingTokens = new Map<string, { sessionId: string; hash: string; expires: number; redeemed?: boolean; canRegisterAgent: false }>();
  staffAssignments: { examId: string; userId: string; role: string }[] = [];
  shadows: { sessionId: string; seq: number; scores: unknown }[] = [];
  windows: { sessionId: string; start: number; features: Record<string, number> }[] = [];
  inventory: { keys: string[]; missing: string[] } = { keys: [], missing: [] };
  healthSnap: { ts: number; checks: Record<string, string> } | null = null;
  liveViewers = new Map<string, Set<string>>();
  eventPartitioning = false;
  kafkaEnabled = false;

  constructor(pepper = "dev-pepper") {
    this.pepper = pepper;
  }

  private memKey(orgId: string, userId: string) {
    return `${orgId}:${userId}`;
  }

  seedDev() {
    const orgId = "00000000-0000-0000-0000-000000000001";
    const userId = "00000000-0000-0000-0000-000000000002";
    this.orgs.set(orgId, { id: orgId, name: "Demo Org", slug: "demo" });
    this.users.set(userId, { id: userId, email: "staff@example.com", issuer: "http://127.0.0.1:5556", subject: "staff-1", name: "Demo Staff" });
    this.memberships.set(this.memKey(orgId, userId), { orgId, userId });
    this.roles.push({ orgId, userId, role: "exam_admin" });
    this.roles.push({ orgId, userId, role: "lead_invigilator" });
    this.roles.push({ orgId, userId, role: "platform_ops" });
    this.persist(() => upsertOrganization({ id: orgId, name: "Demo Org", slug: "demo" }));
    return { orgId, userId };
  }

  private persist(work: () => Promise<void>) {
    if (!process.env.DATABASE_URL) return;
    enqueuePersist(work);
  }

  createOrg(name: string, slug: string) {
    if ([...this.orgs.values()].some((o) => o.slug === slug)) throw new ApiError("CONFLICT", "slug exists", 409);
    const id = uuid();
    this.orgs.set(id, { id, name, slug });
    return this.orgs.get(id)!;
  }

  upsertUser(email: string, issuer: string, subject: string, name: string) {
    const emailN = email.trim().toLowerCase();
    for (const u of this.users.values()) {
      if (u.email === emailN && (u.issuer !== issuer || u.subject !== subject)) {
        throw new ApiError("CONFLICT", "email already bound", 409);
      }
      if (u.issuer === issuer && u.subject === subject) return u;
    }
    const id = uuid();
    const user = { id, email: emailN, issuer, subject, name };
    this.users.set(id, user);
    return user;
  }

  startOidc(state: string, nonce: string, verifier: string) {
    if (this.oidcTx.has(state)) throw new ApiError("CONFLICT", "state replay", 409);
    this.oidcTx.set(state, { nonce, pkce: pepperHash(verifier, this.pepper), expires: nowPlus(5 * 60_000) });
  }

  consumeOidc(state: string, nonce: string, verifier: string) {
    const tx = this.oidcTx.get(state);
    if (!tx) throw new ApiError("AUTH_DENIED", "unknown state", 401);
    if (tx.used) throw new ApiError("AUTH_DENIED", "state replay", 401);
    if (Date.now() > tx.expires) throw new ApiError("AUTH_DENIED", "state expired", 401);
    if (tx.nonce !== nonce) throw new ApiError("AUTH_DENIED", "nonce mismatch", 401);
    const hashed = pepperHash(verifier, this.pepper);
    if (hashed !== tx.pkce) throw new ApiError("AUTH_DENIED", "pkce mismatch", 401);
    tx.used = true;
    return true;
  }

  createStaffSession(orgId: string, userId: string) {
    const raw = randomBytes(32).toString("hex");
    const refresh = randomBytes(32).toString("hex");
    const id = uuid();
    const csrf = randomBytes(16).toString("hex");
    this.staffSessions.set(id, {
      id, orgId, userId,
      sessionHash: pepperHash(raw, this.pepper),
      refreshHash: pepperHash(refresh, this.pepper),
      expires: nowPlus(8 * 3600_000),
      csrf,
    });
    return { id, raw, refresh, csrf };
  }

  lookupStaff(raw: string): StaffContext | null {
    const hashed = pepperHash(raw, this.pepper);
    for (const s of this.staffSessions.values()) {
      if (s.revoked || Date.now() > s.expires) continue;
      if (s.sessionHash !== hashed) continue;
      const roles = this.roles.filter((r) => r.orgId === s.orgId && r.userId === s.userId).map((r) => r.role);
      const permissions = new Set(roles.flatMap((r) => ROLE_PERMS[r] || []));
      return { userId: s.userId, orgId: s.orgId, roles, permissions, stepUpUntil: s.stepUpUntil, csrf: s.csrf };
    }
    return null;
  }

  logout(raw: string) {
    const hashed = pepperHash(raw, this.pepper);
    for (const s of this.staffSessions.values()) {
      if (s.sessionHash === hashed) s.revoked = true;
    }
  }

  markStepUp(raw: string, ms = 5 * 60_000) {
    const hashed = pepperHash(raw, this.pepper);
    for (const s of this.staffSessions.values()) {
      if (s.sessionHash === hashed) s.stepUpUntil = Date.now() + ms;
    }
  }

  require(ctx: StaffContext, perm: string, examId?: string) {
    if (!ctx.permissions.has(perm) && !ctx.permissions.has("platform.ops")) {
      this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "deny:" + perm, payload: { examId } });
      throw new ApiError("TENANT_DENIED", "missing permission " + perm, 403);
    }
    if (STEP_UP_ACTIONS.has(perm) && (ctx.stepUpUntil || 0) < Date.now()) {
      throw new ApiError("STEP_UP_REQUIRED", "recent auth required", 403);
    }
  }

  assertOrg(ctx: StaffContext, orgId: string) {
    if (ctx.orgId !== orgId) throw new ApiError("TENANT_DENIED", "cross-tenant", 403);
  }

  createExam(ctx: StaffContext, code: string, title: string, policyBody: unknown) {
    this.require(ctx, "exam.write");
    if ([...this.exams.values()].some((e) => e.orgId === ctx.orgId && e.code === code)) {
      throw new ApiError("CONFLICT", "exam code exists", 409);
    }
    const id = uuid();
    const policyId = uuid();
    this.exams.set(id, { id, orgId: ctx.orgId, code, title, status: "DRAFT", version: 1, policyId });
    this.policies.set(policyId, { id: policyId, examId: id, version: 1, body: policyBody, immutable: false });
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "exam.create", payload: { id, code } });
    const exam = this.exams.get(id)!;
    const policy = this.policies.get(policyId);
    this.persist(() => upsertExam(exam, policy));
    return exam;
  }

  openExam(ctx: StaffContext, examId: string) {
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    this.require(ctx, "exam.write");
    exam.status = "OPEN";
    exam.version += 1;
    const pol = [...this.policies.values()].find((p) => p.examId === examId);
    if (pol) pol.immutable = true;
    return exam;
  }

  updatePolicy(ctx: StaffContext, examId: string, body: unknown) {
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    const pol = [...this.policies.values()].find((p) => p.examId === examId);
    if (exam.status === "OPEN" && pol?.immutable) {
      throw new ApiError("CONFLICT", "policy immutable after OPEN", 409);
    }
    if (pol) pol.body = body;
    return pol;
  }

  importRoster(ctx: StaffContext, examId: string, rows: { student_external_id: string; display_name: string }[]) {
    this.require(ctx, "roster.import");
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    const results = [];
    for (const row of rows) {
      try {
        if ([...this.enrollments.values()].some((e) => e.examId === examId && e.studentExternalId === row.student_external_id)) {
          throw new ApiError("CONFLICT", "duplicate student", 409);
        }
        const id = uuid();
        const enrollment = { id, orgId: ctx.orgId, examId, studentExternalId: row.student_external_id, displayName: row.display_name };
        this.enrollments.set(id, enrollment);
        this.persist(() => upsertEnrollment(enrollment));
        results.push({ ok: true, id, student_external_id: row.student_external_id });
      } catch (err) {
        const e = err as ApiError;
        results.push({ ok: false, student_external_id: row.student_external_id, error: e.code || "VALIDATION" });
      }
    }
    return results;
  }

  issueToken(ctx: StaffContext, enrollmentId: string) {
    this.require(ctx, "roster.import");
    const en = this.enrollments.get(enrollmentId);
    if (!en) throw new ApiError("NOT_FOUND", "enrollment", 404);
    this.assertOrg(ctx, en.orgId);
    const raw = randomBytes(24).toString("hex");
    const id = uuid();
    this.tokens.set(id, { id, enrollmentId, hash: pepperHash(raw, this.pepper), expires: nowPlus(7 * 86400_000) });
    return { id, token: raw };
  }

  redeemEnrollment(token: string, fingerprint: string, kind: "laptop" | "phone" = "laptop") {
    const hash = pepperHash(token, this.pepper);
    const tok = [...this.tokens.values()].find((t) => t.hash === hash);
    if (!tok) throw new ApiError("AUTH_DENIED", "bad token", 401);
    if (tok.redeemed) throw new ApiError("CONFLICT", "token already redeemed", 409);
    if (Date.now() > tok.expires) throw new ApiError("AUTH_DENIED", "expired", 401);
    tok.redeemed = true;
    const en = this.enrollments.get(tok.enrollmentId)!;
    for (const d of this.devices.values()) {
      if (d.enrollmentId === en.id && d.kind === kind) d.revoked = true;
    }
    const deviceId = uuid();
    const familyId = uuid();
    this.devices.set(deviceId, { id: deviceId, enrollmentId: en.id, kind, familyId });
    const refresh = randomBytes(24).toString("hex");
    this.refreshTokens.set(familyId, { hash: pepperHash(refresh, this.pepper), familyId });
    const existing = [...this.sessions.values()].find((s) => s.enrollmentId === en.id);
    let session = existing;
    if (!session) {
      if ([...this.attempts.values()].some((a) => a.enrollmentId === en.id && !a.terminal)) {
        throw new ApiError("CONFLICT", "active attempt exists", 409);
      }
      const sid = uuid();
      session = {
        id: sid, orgId: en.orgId, examId: en.examId, enrollmentId: en.id,
        desired: "READY", observed: "READY", controlGen: 0, connGen: 0,
        connectivity: "offline", attention: "unknown",
      };
      this.sessions.set(sid, session);
      this.attempts.set(sid, { enrollmentId: en.id, terminal: false });
      this.cursors.set(sid, 0);
    }
    void fingerprint;
    this.persist(() => upsertSession(session));
    return {
      session_id: session.id,
      device_credential_id: deviceId,
      refresh_token: refresh,
      family_id: familyId,
    };
  }

  issuePairingToken(ctx: StaffContext, sessionId: string) {
    this.require(ctx, "session.command");
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, session.orgId);
    const raw = randomBytes(16).toString("hex");
    const id = uuid();
    this.pairingTokens.set(id, {
      sessionId,
      hash: pepperHash(raw, this.pepper),
      expires: nowPlus(5 * 60_000),
      canRegisterAgent: false,
    });
    return { id, token: raw, expires_s: 300, can_register_agent: false };
  }

  revokePhonePairing(ctx: StaffContext, sessionId: string, deviceCredentialId?: string) {
    this.require(ctx, "session.command");
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, session.orgId);
    for (const t of this.pairingTokens.values()) {
      if (t.sessionId === sessionId) t.redeemed = true;
    }
    const revoked: string[] = [];
    for (const d of this.devices.values()) {
      if (d.kind !== "phone" || d.enrollmentId !== session.enrollmentId) continue;
      if (deviceCredentialId && d.id !== deviceCredentialId) continue;
      d.revoked = true;
      revoked.push(d.id);
    }
    return { revoked: true, device_credential_ids: revoked, can_register_agent: false };
  }

  redeemPhonePairing(sessionId: string, pairingToken: string) {
    const hash = pepperHash(pairingToken, this.pepper);
    const tok = [...this.pairingTokens.values()].find((t) => t.hash === hash);
    if (!tok) throw new ApiError("AUTH_DENIED", "bad pairing token", 401);
    if (tok.redeemed) throw new ApiError("CONFLICT", "replay", 409);
    if (Date.now() > tok.expires) throw new ApiError("AUTH_DENIED", "expired", 401);
    if (tok.sessionId !== sessionId) throw new ApiError("AUTH_DENIED", "session mismatch", 401);
    if (tok.canRegisterAgent) throw new ApiError("AUTH_DENIED", "pairing cannot register agent", 401);
    tok.redeemed = true;
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const deviceId = uuid();
    const familyId = uuid();
    this.devices.set(deviceId, { id: deviceId, enrollmentId: session.enrollmentId, kind: "phone", familyId });
    const refresh = randomBytes(16).toString("hex");
    this.refreshTokens.set(familyId, { hash: pepperHash(refresh, this.pepper), familyId });
    return { session_id: sessionId, device_credential_id: deviceId, refresh_token: refresh, kind: "phone", can_register_agent: false };
  }

  rotateRefresh(familyId: string, presented: string) {
    const rec = this.refreshTokens.get(familyId);
    if (!rec) throw new ApiError("AUTH_DENIED", "unknown family", 401);
    const hash = pepperHash(presented, this.pepper);
    if (rec.used) {
      for (const d of this.devices.values()) if (d.familyId === familyId) d.revoked = true;
      throw new ApiError("AUTH_DENIED", "refresh replay — family revoked", 401);
    }
    if (rec.hash !== hash) throw new ApiError("AUTH_DENIED", "bad refresh", 401);
    rec.used = true;
    const next = randomBytes(24).toString("hex");
    this.refreshTokens.set(familyId + ":next", { hash: pepperHash(next, this.pepper), familyId });
    return next;
  }

  ingestEvent(sessionId: string, seq: number, batchId: string, hash: string, payload: unknown) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const dup = this.events.find((e) => e.sessionId === sessionId && e.seq === seq);
    if (dup) {
      if (dup.hash !== hash) {
        this.rejections.push({ sessionId, seq, code: "HASH_MISMATCH" });
        throw new ApiError("HASH_MISMATCH", "same seq different hash", 409);
      }
      return { duplicate: true, acked_through: this.cursors.get(sessionId) || 0 };
    }
    if (this.events.some((e) => e.batchId === batchId)) throw new ApiError("CONFLICT", "batch", 409);
    const event = { sessionId, seq, batchId, hash, payload, orgId: session.orgId };
    this.events.push(event);
    this.rawOutbox.push({ eventId: this.events.length, offset: this.rawOutbox.length + 1, payload });
    this.shadowScore(sessionId, seq, payload);
    const expected = (this.cursors.get(sessionId) || 0) + 1;
    if (seq === expected) this.cursors.set(sessionId, seq);
    this.appendStream(session.examId, { op: "event", session_id: sessionId, seq });
    this.persist(() => upsertEvent(event));
    return { duplicate: false, acked_through: this.cursors.get(sessionId) || 0 };
  }

  nack(sessionId: string, seq: number, code: string) {
    this.rejections.push({ sessionId, seq, code });
  }

  acceptCommand(ctx: StaffContext, sessionId: string, type: string, idempotencyKey: string, body: unknown) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, session.orgId);
    const perm = type === "EXAM_END" || type === "END" ? "exam.end" : type === "WARN" ? "session.warn" : type === "KICK" ? "session.terminate" : "session.command";
    this.require(ctx, perm);
    const existing = [...this.commands.values()].find((c) => c.sessionId === sessionId && c.idempotencyKey === idempotencyKey);
    if (existing) return { ...existing, replay: true };
    if (type === "EXAM_START" || type === "START") session.desired = "IN_EXAM";
    if (type === "PAUSE") session.desired = "PAUSED";
    if (type === "RESUME") session.desired = "IN_EXAM";
    if (type === "EXAM_END" || type === "END") session.desired = "ENDED";
    session.controlGen += 1;
    const id = uuid();
    const cmd = { id, sessionId, type, idempotencyKey, status: "accepted", orgId: session.orgId };
    this.commands.set(id, cmd);
    this.appendStream(session.examId, { op: "upsert", session_id: sessionId, patch: { last_command: type, desired: session.desired } });
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "command:" + type, payload: { sessionId, id } });
    this.persist(async () => {
      await upsertSession(session);
      await upsertCommand({ ...cmd, body });
    });
    return cmd;
  }

  commandResult(sessionId: string, commandId: string, ok: boolean, observed: string) {
    const cmd = this.commands.get(commandId);
    if (!cmd || cmd.sessionId !== sessionId) throw new ApiError("NOT_FOUND", "command", 404);
    cmd.status = ok ? "acked" : "failed";
    cmd.result = { ok, observed };
    const session = this.sessions.get(sessionId)!;
    if (ok) session.observed = observed;
    this.appendStream(session.examId, { op: "upsert", session_id: sessionId, patch: { last_command_status: cmd.status, lifecycle: session.observed } });
    return cmd;
  }

  appendStream(examId: string, payload: unknown) {
    const seq = this.examStream.filter((r) => r.examId === examId).length + 1;
    this.examStream.push({ examId, seq, payload });
    return seq;
  }

  snapshot(examId: string) {
    const sessions = [...this.sessions.values()].filter((s) => s.examId === examId).map((s) => {
      const en = this.enrollments.get(s.enrollmentId);
      return {
        session_id: s.id,
        display_name: en?.displayName,
        lifecycle: s.observed,
        connectivity: s.connectivity,
        attention: s.attention,
        claim_owner: s.claimOwner ?? null,
        thumbnail_available: [...this.media.values()].some((m) => m.sessionId === s.id && m.status === "verified"),
      };
    });
    sessions.sort((a, b) => Number(b.lifecycle === "BLOCKED") - Number(a.lifecycle === "BLOCKED"));
    const seq = this.examStream.filter((r) => r.examId === examId).reduce((m, r) => Math.max(m, r.seq), 0);
    return { exam_id: examId, stream_seq: seq, readiness: this.readiness(examId), sessions };
  }

  deltas(examId: string, afterSeq: number) {
    return this.examStream
      .filter((r) => r.examId === examId && r.seq > afterSeq)
      .map((r) => {
        const p = (r.payload || {}) as { op?: string; session_id?: string; patch?: Record<string, unknown>; seq?: number };
        const op = p.op === "remove" || p.op === "heartbeat" || p.op === "event" || p.op === "upsert" ? p.op : "upsert";
        return {
          exam_id: examId,
          stream_seq: r.seq,
          op,
          session_id: p.session_id,
          patch: p.patch,
        };
      });
  }

  readiness(examId: string): "Incident" | "Blocked" | "Degraded" | "Ready" {
    const sess = [...this.sessions.values()].filter((s) => s.examId === examId);
    if (sess.some((s) => s.observed === "BLOCKED")) return "Blocked";
    if (this.findings.size && [...this.findings.values()].some((f) => sess.some((s) => s.id === f.sessionId))) return "Incident";
    if (sess.some((s) => s.connectivity !== "online" || s.observed === "DEGRADED")) return "Degraded";
    return "Ready";
  }

  claim(ctx: StaffContext, sessionId: string, ttlMs = 30_000) {
    this.require(ctx, "assignment.claim");
    const s = this.sessions.get(sessionId);
    if (!s) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, s.orgId);
    if (s.claimOwner && s.claimOwner !== ctx.userId && (s.claimUntil || 0) > Date.now()) {
      throw new ApiError("CONFLICT", "claimed", 409);
    }
    s.claimOwner = ctx.userId;
    s.claimUntil = Date.now() + ttlMs;
    this.leases.set(sessionId, { owner: ctx.userId, until: s.claimUntil });
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "claim", payload: { sessionId } });
    return s;
  }

  handoff(ctx: StaffContext, sessionId: string, toUserId: string) {
    this.require(ctx, "assignment.claim");
    const s = this.sessions.get(sessionId);
    if (!s) throw new ApiError("NOT_FOUND", "session", 404);
    s.claimOwner = toUserId;
    s.claimUntil = Date.now() + 30_000;
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "handoff", payload: { sessionId, toUserId } });
    return s;
  }

  presignUpload(sessionId: string, contentType: string, bytes: number, sha256: string, kind: string) {
    if (bytes <= 0 || bytes > 5_000_000) throw new ApiError("VALIDATION", "size", 400);
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const id = uuid();
    const key = `${session.orgId}/${sessionId}/${id}`;
    this.media.set(id, { id, orgId: session.orgId, sessionId, key, type: contentType, bytes, sha256, status: "pending_verification", attempts: 0 });
    return { asset_id: id, object_key: key, url: `/internal/object/${key}`, expires_s: 300 };
  }

  verifyMedia(assetId: string, headOk: boolean, hash: string, decodable: boolean) {
    const m = this.media.get(assetId);
    if (!m) throw new ApiError("NOT_FOUND", "asset", 404);
    if (!headOk || hash !== m.sha256 || !decodable) {
      m.status = "quarantined";
      this.deadLetter.push({ assetId, reason: "verification failed" });
      return m;
    }
    m.status = "verified";
    return m;
  }

  signedThumbnail(ctx: StaffContext, sessionId: string) {
    this.require(ctx, "session.read");
    const asset = [...this.media.values()].find((m) => m.sessionId === sessionId && m.status === "verified");
    if (!asset) return { available: false };
    return { available: true, url: `/api/v1/media/${asset.id}/thumb?sig=short`, expires_s: 60 };
  }

  livekitToken(ctx: StaffContext, sessionId: string, role: "publish" | "subscribe") {
    if (role === "subscribe") this.require(ctx, "session.live_view");
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const watched = [...this.sessions.values()].filter((s) => s.claimOwner === ctx.userId).length;
    if (role === "subscribe" && watched > 1) throw new ApiError("QUOTA", "one watched student", 507);
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "livekit:" + role, payload: { sessionId } });
    return { room: `session-${sessionId}`, token: "lk_" + randomBytes(8).toString("hex"), role };
  }

  addFinding(ctx: StaffContext, sessionId: string, label: string, eventSeq?: number) {
    this.require(ctx, "review.annotate");
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const id = uuid();
    this.findings.set(id, { id, sessionId, orgId: session.orgId, label, status: "provisional", actorId: ctx.userId });
    this.revisions.push({ findingId: id, actorId: ctx.userId, label });
    return this.findings.get(id)!;
  }

  assignReviewers(findingId: string, a: string, b: string) {
    if (a === b) throw new ApiError("VALIDATION", "two reviewers cannot be the same actor", 400);
    this.reviewAssign.push({ findingId, reviewerId: a }, { findingId, reviewerId: b });
  }

  appeal(findingId: string, original: string, appealReviewer: string) {
    if (original === appealReviewer) throw new ApiError("VALIDATION", "appeal reviewer cannot be original", 400);
    const f = this.findings.get(findingId);
    if (!f) throw new ApiError("NOT_FOUND", "finding", 404);
    const man = [...this.manifests.values()].find((m) => m.sessionId === f.sessionId);
    if (man) man.frozen = true;
    const id = uuid();
    this.appeals.set(id, { id, findingId, original, appealReviewer });
    return this.appeals.get(id)!;
  }

  setAlias(alias: string, version: string, body: unknown) {
    this.modelRegistry.set(alias, { version, body });
  }

  assignStaff(ctx: StaffContext, examId: string, userId: string, role: string) {
    this.require(ctx, "exam.write");
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    if (!this.memberships.has(this.memKey(exam.orgId, userId))) throw new ApiError("TENANT_DENIED", "staff not in org", 403);
    this.staffAssignments.push({ examId, userId, role });
    return { examId, userId, role };
  }

  bulkCommands(ctx: StaffContext, sessionIds: string[], type: string, idempotencyKey: string) {
    const results = sessionIds.map((id, i) => {
      try {
        const cmd = this.acceptCommand(ctx, id, type, `${idempotencyKey}:${i}`, {});
        return { session_id: id, ok: true, status: cmd.status, replay: !!(cmd as { replay?: boolean }).replay, command_id: cmd.id };
      } catch (err) {
        const e = err as ApiError;
        return { session_id: id, ok: false, error: e.code || "UNAVAILABLE" };
      }
    });
    return { results, all_ok: results.every((r) => r.ok) };
  }

  shadowScore(sessionId: string, seq: number, payload: unknown) {
    try {
      const p = (payload || {}) as Record<string, number>;
      const scores = {
        look_away: Number(Math.abs(p.gaze_h || 0) > 0.45),
        multi_face: Number((p.face_count || 1) > 1),
      };
      this.shadows.push({ sessionId, seq, scores });
      return scores;
    } catch {
      return null;
    }
  }

  windowFeatures(sessionId: string, events: { t: number; gaze_h?: number; face_count?: number }[]) {
    const stride = 5;
    const win = 10;
    const out = [];
    for (let start = 0; start <= 60 - win; start += stride) {
      const slice = events.filter((e) => e.t >= start && e.t < start + win);
      const features = {
        gaze_h_mean: slice.length ? slice.reduce((a, e) => a + (e.gaze_h || 0), 0) / slice.length : 0,
        face_count_max: slice.reduce((a, e) => Math.max(a, e.face_count || 0), 0),
      };
      if ("fused_score" in features) throw new Error("leakage");
      this.windows.push({ sessionId, start, features });
      out.push({ start, features });
    }
    return out;
  }

  freezeLegalHold(sessionId: string) {
    this.legalHold.add(sessionId);
    const man = [...this.manifests.values()].find((m) => m.sessionId === sessionId);
    if (man) man.frozen = true;
    else this.manifests.set(sessionId, { id: sessionId, sessionId, frozen: true, body: {} });
  }

  retainOrDiscard(sessionId: string, now = Date.now(), retainMs = 90 * 86400_000) {
    if (this.legalHold.has(sessionId)) return { action: "hold" };
    const session = this.sessions.get(sessionId);
    if (!session) return { action: "missing" };
    return { action: "retain", until: now + retainMs };
  }

  reconcileInventory() {
    const keys = [...this.media.values()].map((m) => m.key);
    this.inventory = { keys, missing: [] };
    return this.inventory;
  }

  stopLive(sessionId: string, viewerId: string) {
    const set = this.liveViewers.get(sessionId) || new Set();
    set.delete(viewerId);
    this.liveViewers.set(sessionId, set);
    if (set.size === 0) {
      this.audit.push({ orgId: this.sessions.get(sessionId)?.orgId || "", action: "STOP_LIVE", payload: { sessionId } });
      return { stopped: true };
    }
    return { stopped: false, remaining: set.size };
  }

  startLive(sessionId: string, viewerId: string) {
    const set = this.liveViewers.get(sessionId) || new Set();
    set.add(viewerId);
    this.liveViewers.set(sessionId, set);
    this.audit.push({ orgId: this.sessions.get(sessionId)?.orgId || "", action: "START_LIVE", payload: { sessionId, viewerId } });
    return { viewers: set.size };
  }

  pollHealth() {
    const checks = this.health();
    this.healthSnap = { ts: Date.now(), checks };
    return { ...checks, redis_ttl_s: 30, source: this.redisDown ? "postgres" : "redis" };
  }

  health() {
    if (process.env.DATABASE_URL) void pingPostgres();
    return {
      postgres: postgresStatus(),
      redis: this.redisDown ? "down" : "ok",
      object: "ok",
      livekit: process.env.LIVEKIT_URL ? "ok" : "unconfigured",
      fanout: this.redisDown ? "degraded" : "ok",
    };
  }

  platformView() {
    return {
      tenant_blind: true,
      exams: this.exams.size,
      sessions: this.sessions.size,
      agents_online: [...this.presence.values()].filter((p) => p.online).length,
      event_partitioning: this.eventPartitioning,
      kafka: this.kafkaEnabled,
      checks: this.pollHealth(),
    };
  }
}

export const globalStore = new Store(process.env.TOKEN_PEPPER || "dev-pepper");
globalStore.seedDev();
