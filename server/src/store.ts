import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { v4 as uuid } from "uuid";
import { ConsoleStream } from "./console-stream.js";
import {
  enqueuePersist,
  flushPersist,
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

type SessionRecord = {
  id: string; orgId: string; examId: string; enrollmentId: string;
  desired: string; observed: string; controlGen: number; connGen: number;
  connectivity: string; attention: string; claimOwner?: string; claimUntil?: number;
};

type StoredCommand = {
  id: string; sessionId: string; type: string; idempotencyKey: string; status: string;
  result?: unknown; body: Record<string, unknown>; orgId: string; createdAt: number; controlGen: number;
};

const COMMANDS = new Set(["EXAM_START", "EXAM_PAUSE", "EXAM_RESUME", "EXAM_END", "WARN", "REQUEST_CLIP", "UPDATE_POLICY", "KICK", "STOP_LIVE"]);
const COMMAND_ALIASES = new Map([["START", "EXAM_START"], ["PAUSE", "EXAM_PAUSE"], ["RESUME", "EXAM_RESUME"], ["END", "EXAM_END"]]);
const COMMAND_TARGETS = new Map([
  ["EXAM_START", "IN_EXAM"], ["EXAM_PAUSE", "PAUSED"], ["EXAM_RESUME", "IN_EXAM"], ["EXAM_END", "ENDED"],
]);
const EVENT_LIMIT = 5000;
const LIFECYCLE = new Set(["NEW", "ENROLLING", "PRECHECK", "READY", "DEGRADED", "IN_EXAM", "PAUSED", "BLOCKED", "ENDED"]);

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
  devices = new Map<string, { id: string; enrollmentId: string; kind: "laptop" | "phone"; familyId: string; revoked?: boolean; desktop?: boolean }>();
  refreshTokens = new Map<string, { hash: string; familyId: string; used?: boolean }>();
  consents = new Map<string, unknown>();
  sessions = new Map<string, SessionRecord>();
  attempts = new Map<string, { enrollmentId: string; terminal: boolean }>();
  events: { sessionId: string; seq: number; batchId: string; hash: string; payload: unknown; orgId: string }[] = [];
  private recentEvents = new Map<string, Store["events"][number]>();
  private recentBatches = new Set<string>();
  ingestedEventCount = 0;
  rejections: { sessionId: string; seq: number; code: string }[] = [];
  cursors = new Map<string, number>();
  commands = new Map<string, StoredCommand>();
  private commandKeys = new Map<string, StoredCommand>();
  private latestCommands = new Map<string, StoredCommand>();
  private activeCommands = new Map<string, Set<StoredCommand>>();
  private eventWrites = new Map<string, Promise<number | undefined>>();
  readonly examStream = new ConsoleStream();
  media = new Map<string, { id: string; orgId: string; sessionId: string; key: string; type: string; bytes: number; sha256: string; status: string; attempts: number }>();
  deadLetter: { assetId: string; reason: string }[] = [];
  manifests = new Map<string, { id: string; sessionId: string; frozen: boolean; body: unknown }>();
  findings = new Map<string, { id: string; sessionId: string; orgId: string; label: string; status: string; actorId?: string; eventSeq?: number }>();
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
    if (!this.roles.some((row) => row.orgId === orgId && row.userId === userId)) {
      this.roles.push({ orgId, userId, role: "exam_admin" }, { orgId, userId, role: "lead_invigilator" }, { orgId, userId, role: "platform_ops" });
    }
    this.persist(() => upsertOrganization({ id: orgId, name: "Demo Org", slug: "demo" }));
    return { orgId, userId };
  }

  private persist(work: () => Promise<void>) {
    if (!process.env.DATABASE_URL) return;
    void enqueuePersist(work);
  }

  /** Wait for queued writes during validation or shutdown. */
  awaitDurable(): Promise<void> {
    return flushPersist();
  }

  getLatestCommand(sessionId: string) {
    return this.latestCommands.get(sessionId);
  }

  pendingCommands(sessionId: string) {
    return [...(this.activeCommands.get(sessionId) ?? [])];
  }

  pendingCommandsBySession() {
    return this.activeCommands;
  }

  private removePending(cmd: StoredCommand) {
    const pending = this.activeCommands.get(cmd.sessionId);
    pending?.delete(cmd);
    if (!pending?.size) this.activeCommands.delete(cmd.sessionId);
  }

  markDispatched(commandId: string) {
    const cmd = this.commands.get(commandId);
    if (cmd?.status === "accepted") {
      cmd.status = "dispatched";
      const receipt = { ...cmd };
      this.persist(() => upsertCommand(receipt));
      const session = this.sessions.get(cmd.sessionId);
      if (session && this.getLatestCommand(cmd.sessionId) === cmd) {
        this.appendStream(session.examId, { op: "upsert", session_id: cmd.sessionId, patch: { last_command_status: cmd.status } });
      }
    }
    return cmd;
  }

  expireStaleCommands(now = Date.now(), ttlMs = 120_000) {
    let n = 0;
    for (const pending of this.activeCommands.values()) {
      for (const cmd of pending) {
        if (now - cmd.createdAt <= ttlMs) continue;
        cmd.status = "expired";
        this.removePending(cmd);
        this.updateCommandResult(cmd);
        n += 1;
      }
    }
    return n;
  }

  createOrg(name: string, slug: string) {
    if ([...this.orgs.values()].some((o) => o.slug === slug)) throw new ApiError("CONFLICT", "slug exists", 409);
    const id = uuid();
    const organization = { id, name, slug };
    this.orgs.set(id, organization);
    this.persist(() => upsertOrganization(organization));
    return organization;
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

  requireExam(ctx: StaffContext, examId: string, permission = "exam.read") {
    this.require(ctx, permission, examId);
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    return exam;
  }

  private examLink(policy: unknown) {
    const url = (policy as { exam_url?: unknown } | null)?.exam_url;
    if (typeof url !== "string" || !url.trim() || url.length > 2000) return undefined;
    try {
      const parsed = new URL(url.trim());
      const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
      const secure = parsed.protocol === "https:" || (parsed.protocol === "http:" && loopback && process.env.NODE_ENV !== "production");
      if (secure && !parsed.username && !parsed.password) return parsed.href;
    } catch { /* invalid URL */ }
    return undefined;
  }

  examDetails(ctx: StaffContext, examId: string) {
    const exam = this.requireExam(ctx, examId);
    const policy = exam.policyId ? this.policies.get(exam.policyId) : undefined;
    const examUrl = this.examLink(policy?.body);
    const hasSessions = [...this.sessions.values()].some((session) => session.examId === examId);
    return { ...exam, exam_url: examUrl ?? null, exam_url_editable: !hasSessions && !!policy };
  }

  saveExamLink(ctx: StaffContext, examId: string, url: unknown) {
    const exam = this.requireExam(ctx, examId, "exam.write");
    const policy = exam.policyId ? this.policies.get(exam.policyId) : undefined;
    if (!policy || [...this.sessions.values()].some((session) => session.examId === examId)) {
      throw new ApiError("CONFLICT", "The exam website is locked after a candidate enrolls", 409);
    }
    const normalized = this.examLink({ exam_url: url });
    if (url !== null && !normalized) throw new ApiError("VALIDATION", "Enter a valid HTTPS exam link");
    const body = { ...(policy.body as Record<string, unknown>) };
    if (normalized) body.exam_url = normalized;
    else delete body.exam_url;
    policy.body = body;
    this.persist(() => upsertExam(exam, policy));
    return this.examDetails(ctx, examId);
  }

  createExam(ctx: StaffContext, code: string, title: string, policyBody: unknown) {
    this.require(ctx, "exam.write");
    if (typeof code !== "string" || typeof title !== "string" || !code.trim() || !title.trim() || code.length > 60 || title.length > 200) {
      throw new ApiError("VALIDATION", "Exam code and title are required (60 and 200 characters max)");
    }
    const examUrl = (policyBody as { exam_url?: unknown } | null)?.exam_url;
    if (examUrl !== undefined && !this.examLink(policyBody)) throw new ApiError("VALIDATION", "Provide a valid HTTPS exam link");
    code = code.trim();
    title = title.trim();
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
    if (exam.status === "OPEN") return exam;
    exam.status = "OPEN";
    exam.version += 1;
    const pol = [...this.policies.values()].find((p) => p.examId === examId);
    if (pol) pol.immutable = true;
    const updated = { ...exam };
    const policy = pol && { ...pol };
    this.persist(() => upsertExam(updated, policy));
    return exam;
  }

  updatePolicy(ctx: StaffContext, examId: string, body: unknown) {
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    this.require(ctx, "exam.write");
    const pol = [...this.policies.values()].find((p) => p.examId === examId);
    if (exam.status === "OPEN" && pol?.immutable) {
      throw new ApiError("CONFLICT", "policy immutable after OPEN", 409);
    }
    if (pol) {
      pol.body = body;
      const updated = { ...exam };
      const policy = { ...pol };
      this.persist(() => upsertExam(updated, policy));
    }
    return pol;
  }

  importRoster(ctx: StaffContext, examId: string, rows: { student_external_id: string; display_name: string }[]) {
    this.require(ctx, "roster.import");
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    const existing = new Set([...this.enrollments.values()].filter((en) => en.examId === examId).map((en) => en.studentExternalId));
    const results = [];
    for (const row of rows) {
      const studentExternalId = typeof row?.student_external_id === "string" ? row.student_external_id.trim() : "";
      const displayName = typeof row?.display_name === "string" ? row.display_name.trim() : "";
      if (!studentExternalId || !displayName || studentExternalId.length > 200 || displayName.length > 200) {
        results.push({ ok: false, student_external_id: studentExternalId, error: "VALIDATION" });
        continue;
      }
      if (existing.has(studentExternalId)) {
        results.push({ ok: false, student_external_id: studentExternalId, error: "CONFLICT" });
        continue;
      }
      const id = uuid();
      const enrollment = { id, orgId: ctx.orgId, examId, studentExternalId, displayName };
      existing.add(studentExternalId);
      this.enrollments.set(id, enrollment);
      this.persist(() => upsertEnrollment(enrollment));
      results.push({ ok: true, id, student_external_id: studentExternalId });
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

  redeemEnrollment(token: string, fingerprint: string, kind: "laptop" | "phone" = "laptop", desktop = false) {
    if (typeof token !== "string" || !token || (kind !== "laptop" && kind !== "phone")) {
      throw new ApiError("VALIDATION", "An enrollment token and valid device type are required");
    }
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
    this.devices.set(deviceId, { id: deviceId, enrollmentId: en.id, kind, familyId, desktop: desktop && kind === "laptop" });
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
        desired: desktop && kind === "laptop" ? "PRECHECK" : "READY",
        observed: desktop && kind === "laptop" ? "PRECHECK" : "READY", controlGen: 0, connGen: 0,
        connectivity: "offline", attention: "unknown",
      };
      this.sessions.set(sid, session);
      this.attempts.set(sid, { enrollmentId: en.id, terminal: false });
      this.cursors.set(sid, 0);
      this.appendStream(en.examId, { op: "upsert", session_id: sid, patch: this.consoleSession(session, false) });
    }
    void fingerprint;
    this.persist(() => upsertSession(session));
    return {
      session_id: session.id,
      device_credential_id: deviceId,
      refresh_token: refresh,
      family_id: familyId,
      ...(desktop && kind === "laptop" ? {
        exam_title: this.exams.get(session.examId)?.title,
        exam_url: this.examLink(this.desktopPolicy(session)),
        camera_required: this.desktopCameraRequired(session),
      } : {}),
    };
  }

  private desktopPolicy(session: SessionRecord) {
    const policyId = this.exams.get(session.examId)?.policyId;
    return policyId ? this.policies.get(policyId)?.body : undefined;
  }

  private desktopCameraRequired(session: SessionRecord) {
    const policy = this.desktopPolicy(session) as { camera?: boolean; capabilities?: { camera?: boolean } } | undefined;
    return (policy?.capabilities?.camera ?? policy?.camera) === true;
  }

  applyDesktopPrecheck(sessionId: string, cameraReady: boolean) {
    const session = this.sessions.get(sessionId)!;
    const preExam = ["PRECHECK", "READY", "DEGRADED", "BLOCKED"];
    if (!preExam.includes(session.observed) || !preExam.includes(session.desired)) return;
    const lifecycle = this.desktopCameraRequired(session) && !cameraReady ? "BLOCKED" : "READY";
    if (session.observed === lifecycle && session.desired === lifecycle) return;
    session.observed = session.desired = lifecycle;
    session.attention = lifecycle === "BLOCKED" ? "camera_check_required" : "unknown";
    this.appendStream(session.examId, { op: "upsert", session_id: sessionId,
      patch: { lifecycle, desired: lifecycle, attention: session.attention } });
    const state = { ...session };
    this.persist(() => upsertSession(state));
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
    if (!Number.isSafeInteger(seq) || seq < 1 || !batchId || batchId.length > 200 || !/^[a-f0-9]{64}$/i.test(hash)) {
      throw new ApiError("VALIDATION", "Invalid event sequence, batch, or hash");
    }
    const dup = this.recentEvents.get(`${sessionId}:${seq}`);
    if (dup) {
      if (dup.hash !== hash) {
        this.rejections.push({ sessionId, seq, code: "HASH_MISMATCH" });
        throw new ApiError("HASH_MISMATCH", "same seq different hash", 409);
      }
      this.persistEvent(dup);
      return { duplicate: true, acked_through: this.cursors.get(sessionId) || 0 };
    }
    const through = this.cursors.get(sessionId) ?? 0;
    const event = { sessionId, seq, batchId, hash, payload, orgId: session.orgId };
    if (seq <= through) {
      // PostgreSQL still checks the hash for retries older than the in-memory window.
      this.persistEvent(event);
      return { duplicate: true, acked_through: through };
    }
    if (this.recentBatches.has(batchId)) throw new ApiError("CONFLICT", "batch", 409);
    this.events.push(event);
    this.recentEvents.set(`${sessionId}:${seq}`, event);
    this.recentBatches.add(batchId);
    if (this.events.length > EVENT_LIMIT) {
      for (const evicted of this.events.splice(0, 1000)) {
        this.recentEvents.delete(`${evicted.sessionId}:${evicted.seq}`);
        this.recentBatches.delete(evicted.batchId);
      }
    }
    this.ingestedEventCount += 1;
    this.rawOutbox.push({ eventId: this.ingestedEventCount, offset: this.ingestedEventCount, payload });
    if (this.rawOutbox.length > EVENT_LIMIT) this.rawOutbox.splice(0, 1000);
    this.shadowScore(sessionId, seq, payload);
    if (seq === through + 1) {
      let acked = seq;
      while (this.recentEvents.has(`${sessionId}:${acked + 1}`)) acked += 1;
      this.cursors.set(sessionId, acked);
    }
    this.appendStream(session.examId, { op: "event", session_id: sessionId, event_seq: seq });
    this.persistEvent(event);
    return { duplicate: false, acked_through: this.cursors.get(sessionId) || 0 };
  }

  private persistEvent(event: Store["events"][number]) {
    if (!process.env.DATABASE_URL) return;
    const key = `${event.sessionId}:${event.seq}`;
    if (this.eventWrites.has(key)) return;
    const write = enqueuePersist(() => upsertEvent(event));
    this.eventWrites.set(key, write);
    const clear = () => this.eventWrites.delete(key);
    void write.then(clear, clear);
  }

  awaitDurableEvent(sessionId: string, seq: number) {
    return this.eventWrites.get(`${sessionId}:${seq}`);
  }

  nack(sessionId: string, seq: number, code: string) {
    this.rejections.push({ sessionId, seq, code });
  }

  acceptCommand(ctx: StaffContext, sessionId: string, type: string, idempotencyKey: string, body: unknown) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, session.orgId);
    type = COMMAND_ALIASES.get(type) ?? type;
    if (!COMMANDS.has(type) || typeof idempotencyKey !== "string" || !idempotencyKey.trim()) {
      throw new ApiError("VALIDATION", "Invalid command type or missing idempotency key");
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new ApiError("VALIDATION", "Command body must be an object");
    const perm = type === "EXAM_END" ? "exam.end" : type === "WARN" ? "session.warn" : type === "KICK" ? "session.terminate" : "session.command";
    this.require(ctx, perm);
    const key = `${sessionId}:${idempotencyKey}`;
    const existing = this.commandKeys.get(key);
    if (existing) {
      if (existing.type !== type) throw new ApiError("CONFLICT", "Idempotency key already used", 409);
      return { ...existing, replay: true };
    }
    const desired = session.desired;
    const allowed = type === "EXAM_START" ? ["READY", "DEGRADED"]
      : type === "EXAM_PAUSE" ? ["IN_EXAM"]
      : type === "EXAM_RESUME" ? ["PAUSED"]
      : type === "EXAM_END" ? ["READY", "DEGRADED", "IN_EXAM", "PAUSED", "BLOCKED"] : undefined;
    const target = COMMAND_TARGETS.get(type);
    if (type === "EXAM_START" && this.exams.get(session.examId)?.status !== "OPEN") {
      throw new ApiError("CONFLICT", "Open the exam before starting a session", 409);
    }
    if (allowed && (!allowed.includes(desired) || !allowed.includes(session.observed))) {
      throw new ApiError("CONFLICT", "Command conflicts with the current session lifecycle", 409);
    }
    if (target) session.desired = target;
    session.controlGen += 1;
    const id = uuid();
    const cmd: StoredCommand = {
      id, sessionId, type, idempotencyKey, status: "accepted", orgId: session.orgId, createdAt: Date.now(),
      body: body as Record<string, unknown>, controlGen: session.controlGen,
    };
    this.commands.set(id, cmd);
    this.commandKeys.set(key, cmd);
    this.latestCommands.set(sessionId, cmd);
    const pending = this.activeCommands.get(sessionId) ?? new Set<StoredCommand>();
    pending.add(cmd);
    this.activeCommands.set(sessionId, pending);
    this.appendStream(session.examId, { op: "upsert", session_id: sessionId, patch: { last_command: type, last_command_status: cmd.status, desired: session.desired } });
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "command:" + type, payload: { sessionId, id } });
    const state = { ...session };
    const receipt = { ...cmd };
    this.persist(async () => {
      await upsertSession(state);
      await upsertCommand(receipt);
    });
    return cmd;
  }

  commandResult(sessionId: string, commandId: string, ok: boolean, observed?: string) {
    const cmd = this.commands.get(commandId);
    if (!cmd || cmd.sessionId !== sessionId) throw new ApiError("NOT_FOUND", "command", 404);
    if (cmd.status !== "accepted" && cmd.status !== "dispatched") return cmd;
    if (observed !== undefined && !LIFECYCLE.has(observed)) throw new ApiError("VALIDATION", "Invalid observed lifecycle");
    cmd.status = ok ? "acked" : "failed";
    cmd.result = { ok, observed };
    this.removePending(cmd);
    this.updateCommandResult(cmd, observed);
    return cmd;
  }

  private updateCommandResult(cmd: StoredCommand, observed?: string) {
    const session = this.sessions.get(cmd.sessionId)!;
    const target = COMMAND_TARGETS.get(cmd.type);
    if (target && session.desired === target) {
      if (cmd.status === "acked") session.observed = observed ?? target;
      session.desired = session.observed;
    }
    const lastCommand = this.getLatestCommand(cmd.sessionId);
    this.appendStream(session.examId, { op: "upsert", session_id: cmd.sessionId, patch: {
      last_command: lastCommand?.type, last_command_status: lastCommand?.status, lifecycle: session.observed, desired: session.desired,
    } });
    const state = { ...session };
    const receipt = { ...cmd };
    this.persist(async () => {
      await upsertSession(state);
      await upsertCommand(receipt);
    });
  }


  appendStream(examId: string, change: Parameters<ConsoleStream["append"]>[1]) {
    return this.examStream.append(examId, change);
  }

  updateConnectivity(sessionId: string, connectivity: "online" | "offline") {
    const session = this.sessions.get(sessionId);
    if (!session) return;
    this.presence.set(sessionId, { online: connectivity === "online", ts: Date.now() });
    if (session.connectivity === connectivity) return;
    session.connectivity = connectivity;
    this.appendStream(session.examId, { op: "upsert", session_id: sessionId, patch: { connectivity } });
    this.persist(() => upsertSession(session));
  }

  private consoleSession(session: SessionRecord, hasThumbnail: boolean) {
    const lastCommand = this.getLatestCommand(session.id);
    return {
      session_id: session.id,
      display_name: this.enrollments.get(session.enrollmentId)?.displayName,
      lifecycle: session.observed,
      desired: session.desired,
      connectivity: session.connectivity,
      attention: session.attention,
      claim_owner: session.claimOwner ?? null,
      thumbnail_available: hasThumbnail,
      ...(lastCommand && { last_command: lastCommand.type, last_command_status: lastCommand.status }),
    };
  }

  snapshot(examId: string, opts?: { cursor?: number; limit?: number }) {
    const sessions = [...this.sessions.values()].filter((s) => s.examId === examId);
    // Insertion order keeps offset pages stable when a lifecycle or attention state changes.
    const cursor = Math.max(0, opts?.cursor || 0);
    const limit = Math.min(Math.max(opts?.limit || 200, 1), 500);
    const page = sessions.slice(cursor, cursor + limit);
    const pageIds = new Set(page.map((s) => s.id));
    const thumbnails = new Set<string>();
    for (const item of this.media.values()) {
      if (item.status === "verified" && pageIds.has(item.sessionId)) thumbnails.add(item.sessionId);
    }
    return {
      exam_id: examId,
      stream_id: this.examStream.id,
      stream_seq: this.examStream.head(examId),
      readiness: this.readiness(examId, sessions),
      sessions: page.map((s) => this.consoleSession(s, thumbnails.has(s.id))),
      next_cursor: cursor + page.length,
      total: sessions.length,
    };
  }

  deltas(examId: string, afterSeq: number) {
    return this.examStream.since(examId, afterSeq).items;
  }

  consoleUpdates(examId: string, afterSeq: number, streamId?: string) {
    return { ...this.examStream.since(examId, afterSeq, streamId), readiness: this.readiness(examId) };
  }

  readiness(examId: string, sessions = [...this.sessions.values()].filter((s) => s.examId === examId)): "Incident" | "Blocked" | "Degraded" | "Ready" {
    if (sessions.some((s) => s.observed === "BLOCKED")) return "Blocked";
    if (this.findings.size) {
      const sessionIds = new Set(sessions.map((s) => s.id));
      if ([...this.findings.values()].some((f) => sessionIds.has(f.sessionId))) return "Incident";
    }
    if (sessions.some((s) => s.connectivity !== "online" || s.observed === "DEGRADED")) return "Degraded";
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
    this.setClaim(s, ctx.userId, ttlMs);
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "claim", payload: { sessionId } });
    return s;
  }

  handoff(ctx: StaffContext, sessionId: string, toUserId: string) {
    this.require(ctx, "assignment.claim");
    const s = this.sessions.get(sessionId);
    if (!s) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, s.orgId);
    this.setClaim(s, toUserId, 30_000);
    this.audit.push({ orgId: ctx.orgId, actorId: ctx.userId, action: "handoff", payload: { sessionId, toUserId } });
    return s;
  }

  private setClaim(session: SessionRecord, userId: string, ttlMs: number) {
    const changed = session.claimOwner !== userId;
    session.claimOwner = userId;
    session.claimUntil = Date.now() + ttlMs;
    this.leases.set(session.id, { owner: userId, until: session.claimUntil });
    if (changed) this.appendStream(session.examId, { op: "upsert", session_id: session.id, patch: { claim_owner: userId } });
  }

  expireClaims(now = Date.now()) {
    for (const [sessionId, lease] of this.leases) {
      if (lease.until > now) continue;
      this.leases.delete(sessionId);
      const session = this.sessions.get(sessionId);
      if (!session) continue;
      delete session.claimOwner;
      delete session.claimUntil;
      this.appendStream(session.examId, { op: "upsert", session_id: sessionId, patch: { claim_owner: null } });
    }
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
    const wasVerified = m.status === "verified";
    const verified = headOk && hash === m.sha256 && decodable;
    m.status = verified ? "verified" : "quarantined";
    if (!verified) this.deadLetter.push({ assetId, reason: "verification failed" });
    const session = this.sessions.get(m.sessionId);
    if (session && wasVerified !== verified) {
      const available = verified || [...this.media.values()].some((item) => item.sessionId === session.id && item.status === "verified");
      this.appendStream(session.examId, { op: "upsert", session_id: session.id, patch: { thumbnail_available: available } });
    }
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
    this.assertOrg(ctx, session.orgId);
    if (typeof label !== "string" || !label.trim() || label.length > 200) throw new ApiError("VALIDATION", "Finding label is required (200 characters max)");
    if (eventSeq !== undefined) {
      if (!Number.isSafeInteger(eventSeq) || eventSeq < 1) throw new ApiError("VALIDATION", "Invalid evidence sequence");
      if (!this.recentEvents.has(`${sessionId}:${eventSeq}`)) {
        throw new ApiError("NOT_FOUND", "Evidence event unavailable for this session", 404);
      }
    }
    label = label.trim();
    const id = uuid();
    this.findings.set(id, { id, sessionId, orgId: session.orgId, label, status: "provisional", actorId: ctx.userId, eventSeq });
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

  bulkCommands(ctx: StaffContext, sessionIds: string[], type: string, idempotencyKey: string, examId?: string) {
    const results = sessionIds.map((id) => {
      try {
        if (examId && this.sessions.get(id)?.examId !== examId) throw new ApiError("NOT_FOUND", "session in exam", 404);
        const cmd = this.acceptCommand(ctx, id, type, idempotencyKey, {});
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
      if (this.shadows.length > EVENT_LIMIT) this.shadows.splice(0, 1000);
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
    return { ...checks, source: "process" };
  }

  health() {
    if (process.env.DATABASE_URL) void pingPostgres();
    return {
      postgres: postgresStatus(),
      redis: this.redisDown ? "down" : process.env.REDIS_URL ? "unverified" : "unconfigured",
      object: process.env.OBJECT_STORE_ENDPOINT ? "unverified" : "unconfigured",
      livekit: process.env.LIVEKIT_URL ? "unverified" : "unconfigured",
      fanout: this.redisDown ? "degraded" : "local",
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
