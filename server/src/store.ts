import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { v4 as uuid } from "uuid";
import {
  enqueuePersist,
  freezeManifest,
  insertAudit,
  insertCommandDelivery,
  insertDeadLetter,
  insertEventRejection,
  insertExamStream,
  insertLabelRevision,
  insertOutbox,
  insertReviewAssignment,
  insertSessionAttempt,
  insertStatusTransition,
  markRefreshUsed,
  ping as pingPostgres,
  postgresStatus,
  upsertAppeal,
  upsertAnswer,
  upsertAssignment,
  upsertBank,
  upsertCandidateCode,
  upsertCandidateGroup,
  upsertCandidateSession,
  upsertCommand,
  upsertContentVersion,
  publishContentVersion,
  upsertDeviceTree,
  upsertEnrollment,
  upsertEnrollmentToken,
  upsertEvent,
  upsertEvidenceManifest,
  upsertExam,
  upsertExamContent,
  upsertFinding,
  upsertGroup,
  upsertIngestCursor,
  upsertMediaAsset,
  upsertMediaUpload,
  upsertMembership,
  upsertOrganization,
  upsertReviewCase,
  upsertRoleAssignment,
  upsertSession,
  upsertStaffAssignment,
  upsertStaffSession,
  upsertUserAccount,
  upsertVariantWithOptions,
} from "./db/persist.js";
import { mintLiveKitToken, objectStoreConfigured, presignUrl } from "./media.js";

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

/** Constant-time hex/string comparison (length-guarded). */
function hashEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
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
  users = new Map<string, { id: string; email: string; issuer: string; subject: string; name: string; passwordHash?: string }>();
  memberships = new Map<string, { orgId: string; userId: string }>();
  roles: { orgId: string; userId: string; role: Role; examId?: string }[] = [];
  staffSessions = new Map<string, { id: string; orgId: string; userId: string; sessionHash: string; refreshHash: string; expires: number; revoked?: boolean; replay?: boolean; stepUpUntil?: number; csrf: string }>();
  oidcTx = new Map<string, { nonce: string; pkce: string; verifier: string; used?: boolean; expires: number }>();
  audit: { orgId: string; actorId?: string; action: string; payload: unknown }[] = [];
  exams = new Map<string, {
    id: string; orgId: string; code: string; title: string; status: string; version: number; policyId?: string;
    contentVersionId?: string; allowBackNavigation?: boolean; durationS?: number;
  }>();
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
    connectivity: string; attention: string; claimOwner?: string; claimUntil?: number; startedAt?: number;
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
  banks = new Map<string, { id: string; orgId: string; name: string }>();
  qgroups = new Map<string, { id: string; orgId: string; bankId: string; position: number; title: string; marks: number; negativeMarks: number; rubric: string }>();
  contentVersions = new Map<string, { id: string; orgId: string; bankId: string; version: number }>();
  variants = new Map<string, {
    id: string; orgId: string; groupId: string; contentVersionId?: string;
    position: number; stem: string; qtype: string; perQuestionS?: number; deprecated?: boolean;
  }>();
  qoptions = new Map<string, { id: string; orgId: string; variantId: string; position: number; label: string; correct: boolean }>();
  candidateCodes = new Map<string, { id: string; enrollmentId: string; hash: string; expires: number; redeemed?: boolean; uses: number; maxUses: number }>();
  candidateSessions = new Map<string, { id: string; sessionId: string; enrollmentId: string; hash: string; expires: number; revoked?: boolean; csrf: string }>();
  assignments = new Map<string, { sessionId: string; groupId: string; variantId: string; optionSeed: number; position: number }>();
  answers = new Map<string, { id: string; sessionId: string; variantId: string; optionIds: string[]; textAnswer: string; correct?: boolean; score?: number }>();

  constructor(pepper = "dev-pepper") {
    this.pepper = pepper;
  }

  private memKey(orgId: string, userId: string) {
    return `${orgId}:${userId}`;
  }

  seedDev() {
    const orgId = "00000000-0000-0000-0000-000000000001";
    const userId = "00000000-0000-0000-0000-000000000002";
    if (this.orgs.has(orgId) && this.users.has(userId)) return { orgId, userId };
    this.orgs.set(orgId, { id: orgId, name: "Demo Org", slug: "demo" });
    this.users.set(userId, { id: userId, email: "staff@example.com", issuer: "http://127.0.0.1:5556", subject: "staff-1", name: "Demo Staff" });
    this.addMembership(orgId, userId);
    this.roles.push({ orgId, userId, role: "exam_admin" });
    this.roles.push({ orgId, userId, role: "lead_invigilator" });
    this.roles.push({ orgId, userId, role: "platform_ops" });
    this.persist(() => upsertOrganization({ id: orgId, name: "Demo Org", slug: "demo" }));
    const demoUser = this.users.get(userId)!;
    this.persist(() => upsertUserAccount({ ...demoUser, email: demoUser.email }));
    this.persist(() => upsertMembership(orgId, userId));
    for (const role of ["exam_admin", "lead_invigilator", "platform_ops"] as const) {
      this.persist(() => upsertRoleAssignment({ orgId, userId, role }));
    }
    return { orgId, userId };
  }

  private persist(work: () => Promise<void>) {
    if (!process.env.DATABASE_URL) return;
    enqueuePersist(work);
  }

  /** Append an audit record (memory + durable audit_action). */
  recordAudit(entry: { orgId: string; actorId?: string; action: string; payload: unknown }) {
    this.audit.push(entry);
    this.persist(() => insertAudit(entry));
  }

  createOrg(name: string, slug: string) {
    if ([...this.orgs.values()].some((o) => o.slug === slug)) throw new ApiError("CONFLICT", "slug exists", 409);
    const id = uuid();
    this.orgs.set(id, { id, name, slug });
    this.persist(() => upsertOrganization({ id, name, slug }));
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
    const user: { id: string; email: string; issuer: string; subject: string; name: string; passwordHash?: string } = {
      id, email: emailN, issuer, subject, name,
    };
    this.users.set(id, user);
    this.persist(() => upsertUserAccount(user));
    return user;
  }

  addMembership(orgId: string, userId: string) {
    this.memberships.set(this.memKey(orgId, userId), { orgId, userId });
    this.persist(() => upsertMembership(orgId, userId));
  }

  startOidc(state: string, nonce: string, verifier: string) {
    if (this.oidcTx.has(state)) throw new ApiError("CONFLICT", "state replay", 409);
    this.oidcTx.set(state, { nonce, pkce: pepperHash(verifier, this.pepper), verifier, expires: nowPlus(5 * 60_000) });
  }

  /** Validate a tx and consume it, returning the server-side secrets for code exchange. */
  takeOidcTx(state: string): { nonce: string; verifier: string } {
    const tx = this.oidcTx.get(state);
    if (!tx) throw new ApiError("AUTH_DENIED", "unknown state", 401);
    if (tx.used) throw new ApiError("AUTH_DENIED", "state replay", 401);
    if (Date.now() > tx.expires) throw new ApiError("AUTH_DENIED", "state expired", 401);
    tx.used = true;
    return { nonce: tx.nonce, verifier: tx.verifier };
  }

  consumeOidc(state: string, nonce: string, verifier: string) {
    const tx = this.oidcTx.get(state);
    if (!tx) throw new ApiError("AUTH_DENIED", "unknown state", 401);
    if (tx.used) throw new ApiError("AUTH_DENIED", "state replay", 401);
    if (Date.now() > tx.expires) throw new ApiError("AUTH_DENIED", "state expired", 401);
    if (tx.nonce !== nonce) throw new ApiError("AUTH_DENIED", "nonce mismatch", 401);
    const hashed = pepperHash(verifier, this.pepper);
    if (!hashEqual(hashed, tx.pkce)) throw new ApiError("AUTH_DENIED", "pkce mismatch", 401);
    tx.used = true;
    return true;
  }

  createStaffSession(orgId: string, userId: string) {
    const raw = randomBytes(32).toString("hex");
    const refresh = randomBytes(32).toString("hex");
    const id = uuid();
    const csrf = randomBytes(16).toString("hex");
    const rec = {
      id, orgId, userId,
      sessionHash: pepperHash(raw, this.pepper),
      refreshHash: pepperHash(refresh, this.pepper),
      expires: nowPlus(8 * 3600_000),
      csrf,
    };
    this.staffSessions.set(id, rec);
    this.persist(() => upsertStaffSession({
      id, orgId, userId,
      sessionHash: rec.sessionHash,
      refreshHash: rec.refreshHash,
      expiresAt: rec.expires,
      csrf,
    }));
    return { id, raw, refresh, csrf };
  }

  findUser(issuer: string, subject: string) {
    for (const u of this.users.values()) {
      if (u.issuer === issuer && u.subject === subject) return u;
    }
    return null;
  }

  membershipsFor(userId: string) {
    const out: { orgId: string; userId: string; org: { id: string; name: string; slug: string } | undefined }[] = [];
    for (const m of this.memberships.values()) {
      if (m.userId === userId) out.push({ ...m, org: this.orgs.get(m.orgId) });
    }
    return out;
  }

  syncUserProfile(userId: string, email: string, name: string) {
    const user = this.users.get(userId);
    if (!user) return;
    const emailN = email.trim().toLowerCase();
    for (const u of this.users.values()) {
      if (u.id !== userId && u.email === emailN && (u.issuer !== user.issuer || u.subject !== user.subject)) {
        throw new ApiError("CONFLICT", "email already bound", 409);
      }
    }
    user.email = emailN;
    user.name = name;
  }

  /** One-time bootstrap of the first platform admin. Refuses when any user exists. */
  bootstrapAdmin(email: string, name: string, issuer: string, subject: string) {
    if (this.users.size > 0) throw new ApiError("CONFLICT", "users already exist", 409);
    const orgId = uuid();
    this.orgs.set(orgId, { id: orgId, name: "Primary", slug: "primary" });
    const user = this.upsertUser(email, issuer, subject, name);
    this.addMembership(orgId, user.id);
    this.roles.push({ orgId, userId: user.id, role: "platform_ops" });
    this.roles.push({ orgId, userId: user.id, role: "exam_admin" });
    this.persist(() => upsertUserAccount({ ...user }));
    this.persist(() => upsertRoleAssignment({ orgId, userId: user.id, role: "platform_ops" }));
    this.persist(() => upsertRoleAssignment({ orgId, userId: user.id, role: "exam_admin" }));
    this.persist(() => upsertOrganization({ id: orgId, name: "Primary", slug: "primary" }));
    return { orgId, userId: user.id };
  }

  lookupStaff(raw: string): StaffContext | null {
    for (const s of this.staffSessions.values()) {
      if (s.revoked || Date.now() > s.expires) continue;
      if (!hashEqual(s.sessionHash, pepperHash(raw, this.pepper))) continue;
      const roles = this.roles.filter((r) => r.orgId === s.orgId && r.userId === s.userId).map((r) => r.role);
      const permissions = new Set(roles.flatMap((r) => ROLE_PERMS[r] || []));
      return { userId: s.userId, orgId: s.orgId, roles, permissions, stepUpUntil: s.stepUpUntil, csrf: s.csrf };
    }
    return null;
  }

  logout(raw: string) {
    for (const s of this.staffSessions.values()) {
      if (hashEqual(s.sessionHash, pepperHash(raw, this.pepper))) {
        s.revoked = true;
        this.persist(() => upsertStaffSession({
          id: s.id, orgId: s.orgId, userId: s.userId,
          sessionHash: s.sessionHash, refreshHash: s.refreshHash,
          expiresAt: s.expires, revoked: true, stepUpUntil: s.stepUpUntil, csrf: s.csrf,
        }));
      }
    }
  }

  markStepUp(raw: string, ms = 5 * 60_000) {
    for (const s of this.staffSessions.values()) {
      if (hashEqual(s.sessionHash, pepperHash(raw, this.pepper))) {
        s.stepUpUntil = Date.now() + ms;
        this.persist(() => upsertStaffSession({
          id: s.id, orgId: s.orgId, userId: s.userId,
          sessionHash: s.sessionHash, refreshHash: s.refreshHash,
          expiresAt: s.expires, revoked: s.revoked, stepUpUntil: s.stepUpUntil, csrf: s.csrf,
        }));
      }
    }
  }

  require(ctx: StaffContext, perm: string, examId?: string) {
    if (!ctx.permissions.has(perm) && !ctx.permissions.has("platform.ops")) {
      this.recordAudit({ orgId: ctx.orgId, actorId: ctx.userId, action: "deny:" + perm, payload: { examId } });
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
    this.recordAudit({ orgId: ctx.orgId, actorId: ctx.userId, action: "exam.create", payload: { id, code } });
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
    this.persist(() => upsertExam(exam, pol));
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
    if (pol) {
      pol.body = body;
      const examRef = this.exams.get(examId)!;
      this.persist(() => upsertExam(examRef, pol));
    }
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
    const rec = { id, enrollmentId, hash: pepperHash(raw, this.pepper), expires: nowPlus(7 * 86400_000) };
    this.tokens.set(id, rec);
    this.persist(() => upsertEnrollmentToken({
      id, enrollmentId, tokenHash: rec.hash, expiresAt: rec.expires,
    }));
    return { id, token: raw };
  }

  redeemEnrollment(token: string, fingerprint: string, kind: "laptop" | "phone" = "laptop") {
    const hash = pepperHash(token, this.pepper);
    const tok = [...this.tokens.values()].find((t) => t.hash === hash);
    if (!tok) throw new ApiError("AUTH_DENIED", "bad token", 401);
    if (tok.redeemed) throw new ApiError("CONFLICT", "token already redeemed", 409);
    if (Date.now() > tok.expires) throw new ApiError("AUTH_DENIED", "expired", 401);
    tok.redeemed = true;
    this.persist(() => upsertEnrollmentToken({
      id: tok.id, enrollmentId: tok.enrollmentId, tokenHash: tok.hash,
      expiresAt: tok.expires, redeemed: true,
    }));
    const en = this.enrollments.get(tok.enrollmentId)!;
    for (const d of this.devices.values()) {
      if (d.enrollmentId === en.id && d.kind === kind) d.revoked = true;
    }
    const deviceId = uuid();
    const familyId = uuid();
    this.devices.set(deviceId, { id: deviceId, enrollmentId: en.id, kind, familyId });
    const refresh = randomBytes(24).toString("hex");
    const refreshHash = pepperHash(refresh, this.pepper);
    this.refreshTokens.set(familyId, { hash: refreshHash, familyId });
    this.persist(() => upsertDeviceTree({
      device: { id: deviceId, orgId: en.orgId, enrollmentId: en.id, kind },
      familyId, refreshHash,
    }));
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
      const created = session;
      this.persist(() => upsertSession(created));
      this.persist(() => insertSessionAttempt({ id: sid, sessionId: sid, enrollmentId: en.id, terminal: false }));
      this.persist(() => upsertIngestCursor(sid, 0));
    }
    void fingerprint;
    const persistedSession = session;
    if (!persistedSession) throw new ApiError("NOT_FOUND", "session", 404);
    this.persist(() => upsertSession(persistedSession));
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
    if (!hashEqual(rec.hash, hash)) throw new ApiError("AUTH_DENIED", "bad refresh", 401);
    rec.used = true;
    this.persist(() => markRefreshUsed(rec.hash));
    const next = randomBytes(24).toString("hex");
    const nextHash = pepperHash(next, this.pepper);
    this.refreshTokens.set(familyId + ":next", { hash: nextHash, familyId });
    const famDevice = [...this.devices.values()].find((d) => d.familyId === familyId);
    if (famDevice) {
      const en = this.enrollments.get(famDevice.enrollmentId);
      this.persist(() => upsertDeviceTree({
        device: { id: famDevice.id, orgId: en?.orgId || "", enrollmentId: famDevice.enrollmentId, kind: famDevice.kind },
        familyId, refreshId: `${familyId}:${Date.now()}`, refreshHash: nextHash,
      }));
    }
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
    this.persist(() => upsertIngestCursor(sessionId, this.cursors.get(sessionId) || 0));
    return { duplicate: false, acked_through: this.cursors.get(sessionId) || 0 };
  }

  nack(sessionId: string, seq: number, code: string) {
    this.rejections.push({ sessionId, seq, code });
    this.persist(() => insertEventRejection({ sessionId, seq, code }));
  }

  acceptCommand(ctx: StaffContext, sessionId: string, type: string, idempotencyKey: string, body: unknown) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, session.orgId);
    const perm = type === "EXAM_END" || type === "END" ? "exam.end" : type === "WARN" ? "session.warn" : type === "KICK" ? "session.terminate" : "session.command";
    this.require(ctx, perm);
    const existing = [...this.commands.values()].find((c) => c.sessionId === sessionId && c.idempotencyKey === idempotencyKey);
    if (existing) return { ...existing, replay: true };
    const fromState = session.desired;
    if (type === "EXAM_START" || type === "START") {
      session.desired = "IN_EXAM";
      if (!session.startedAt) session.startedAt = Date.now();
    }
    if (type === "PAUSE") session.desired = "PAUSED";
    if (type === "RESUME") session.desired = "IN_EXAM";
    if (type === "EXAM_END" || type === "END") session.desired = "ENDED";
    session.controlGen += 1;
    const id = uuid();
    const cmd = { id, sessionId, type, idempotencyKey, status: "accepted", orgId: session.orgId };
    this.commands.set(id, cmd);
    this.appendStream(session.examId, { op: "upsert", session_id: sessionId, patch: { last_command: type, desired: session.desired } });
    this.recordAudit({ orgId: ctx.orgId, actorId: ctx.userId, action: "command:" + type, payload: { sessionId, id } });
    this.persist(async () => {
      await upsertSession(session);
      await upsertCommand({ ...cmd, body });
      await insertCommandDelivery({ commandId: id, attempt: 1 });
      await insertStatusTransition({ sessionId, fromState, toState: session.desired, desired: true });
    });
    return cmd;
  }

  commandResult(sessionId: string, commandId: string, ok: boolean, observed: string) {
    const cmd = this.commands.get(commandId);
    if (!cmd || cmd.sessionId !== sessionId) throw new ApiError("NOT_FOUND", "command", 404);
    cmd.status = ok ? "acked" : "failed";
    cmd.result = { ok, observed };
    const session = this.sessions.get(sessionId)!;
    const fromObserved = session.observed;
    if (ok) session.observed = observed;
    this.appendStream(session.examId, { op: "upsert", session_id: sessionId, patch: { last_command_status: cmd.status, lifecycle: session.observed } });
    this.persist(async () => {
      await upsertCommand({ ...cmd });
      await upsertSession(session);
      if (ok && fromObserved !== observed) {
        await insertStatusTransition({ sessionId, fromState: fromObserved, toState: observed, desired: false });
      }
    });
    return cmd;
  }

  appendStream(examId: string, payload: unknown) {
    const seq = this.examStream.filter((r) => r.examId === examId).length + 1;
    this.examStream.push({ examId, seq, payload });
    this.persist(() => insertExamStream(examId, seq, payload));
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
    this.recordAudit({ orgId: ctx.orgId, actorId: ctx.userId, action: "claim", payload: { sessionId } });
    this.persist(() => upsertSession(s));
    return s;
  }

  handoff(ctx: StaffContext, sessionId: string, toUserId: string) {
    this.require(ctx, "assignment.claim");
    const s = this.sessions.get(sessionId);
    if (!s) throw new ApiError("NOT_FOUND", "session", 404);
    s.claimOwner = toUserId;
    s.claimUntil = Date.now() + 30_000;
    this.recordAudit({ orgId: ctx.orgId, actorId: ctx.userId, action: "handoff", payload: { sessionId, toUserId } });
    this.persist(() => upsertSession(s));
    return s;
  }

  presignUpload(
    sessionId: string,
    contentType: string,
    bytes: number,
    sha256: string,
    kind: string,
    opts: { fakeUrl?: boolean } = {},
  ) {
    if (bytes <= 0 || bytes > 5_000_000) throw new ApiError("VALIDATION", "size", 400);
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const id = uuid();
    const key = `${session.orgId}/${sessionId}/${id}`;
    const asset = { id, orgId: session.orgId, sessionId, key, type: contentType, bytes, sha256, status: "pending_verification", attempts: 0 };
    this.media.set(id, asset);
    this.persist(() => upsertMediaAsset({
      id, orgId: asset.orgId, sessionId, kind: "upload",
      objectKey: key, contentType, bytes, sha256, status: asset.status,
    }));
    this.persist(() => upsertMediaUpload({ id: uuid(), assetId: id, expiresAt: Date.now() + 300_000 }));
    const osc = {
      endpoint: process.env.OBJECT_STORE_ENDPOINT || "http://127.0.0.1:9000",
      bucket: process.env.OBJECT_STORE_BUCKET || "phone-proctor",
      region: process.env.OBJECT_STORE_REGION || "us-east-1",
      accessKey: process.env.OBJECT_STORE_ACCESS_KEY,
      secretKey: process.env.OBJECT_STORE_SECRET_KEY,
    };
    let url: string;
    if (objectStoreConfigured(osc)) {
      url = presignUrl(osc, "PUT", key, { contentType, expiresS: 300 });
    } else if (opts.fakeUrl) {
      url = `/internal/object/${key}`;
    } else {
      throw new ApiError("MEDIA_UNCONFIGURED", "object store not configured", 503);
    }
    void kind;
    return { asset_id: id, object_key: key, url, expires_s: 300 };
  }

  verifyMedia(assetId: string, headOk: boolean, hash: string, decodable: boolean) {
    const m = this.media.get(assetId);
    if (!m) throw new ApiError("NOT_FOUND", "asset", 404);
    if (!headOk || hash !== m.sha256 || !decodable) {
      m.status = "quarantined";
      this.deadLetter.push({ assetId, reason: "verification failed" });
      this.persist(() => upsertMediaAsset({
        id: m.id, orgId: m.orgId, sessionId: m.sessionId, kind: "upload",
        objectKey: m.key, contentType: m.type, bytes: m.bytes, sha256: m.sha256, status: m.status,
      }));
      this.persist(() => insertDeadLetter(assetId, "verification failed"));
      return m;
    }
    m.status = "verified";
    this.persist(() => upsertMediaAsset({
      id: m.id, orgId: m.orgId, sessionId: m.sessionId, kind: "upload",
      objectKey: m.key, contentType: m.type, bytes: m.bytes, sha256: m.sha256, status: m.status,
    }));
    return m;
  }

  signedThumbnail(ctx: StaffContext, sessionId: string) {
    this.require(ctx, "session.read");
    const asset = [...this.media.values()].find((m) => m.sessionId === sessionId && m.status === "verified");
    if (!asset) return { available: false as const };
    return { available: true as const, asset_id: asset.id, expires_s: 60 };
  }

  async livekitToken(
    ctx: StaffContext,
    sessionId: string,
    role: "publish" | "subscribe",
    opts: { fake?: boolean } = {},
  ) {
    if (role === "subscribe") this.require(ctx, "session.live_view");
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const watched = [...this.sessions.values()].filter((s) => s.claimOwner === ctx.userId).length;
    if (role === "subscribe" && watched > 1) throw new ApiError("QUOTA", "one watched student", 507);
    this.recordAudit({ orgId: ctx.orgId, actorId: ctx.userId, action: "livekit:" + role, payload: { sessionId } });
    const room = `session-${sessionId}`;
    const identity = role === "publish" ? `agent-${sessionId}` : `staff-${ctx.userId}`;
    if (process.env.LIVEKIT_URL && process.env.LIVEKIT_API_KEY && process.env.LIVEKIT_API_SECRET) {
      const token = await mintLiveKitToken(
        { apiKey: process.env.LIVEKIT_API_KEY, apiSecret: process.env.LIVEKIT_API_SECRET },
        { room, identity, canPublish: role === "publish", canSubscribe: true },
      );
      return { room, token, role, url: process.env.LIVEKIT_URL };
    }
    if (opts.fake) return { room, token: "lk_" + randomBytes(8).toString("hex"), role };
    throw new ApiError("LIVEKIT_UNCONFIGURED", "live view not configured", 503);
  }

  addFinding(ctx: StaffContext, sessionId: string, label: string, eventSeq?: number) {
    this.require(ctx, "review.annotate");
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const id = uuid();
    this.findings.set(id, { id, sessionId, orgId: session.orgId, label, status: "provisional", actorId: ctx.userId });
    this.revisions.push({ findingId: id, actorId: ctx.userId, label });
    this.persist(() => upsertFinding({
      id, orgId: session.orgId, sessionId, eventSeq, label, status: "provisional", actorId: ctx.userId,
    }));
    this.persist(() => insertLabelRevision({ findingId: id, actorId: ctx.userId, label }));
    return this.findings.get(id)!;
  }

  assignReviewers(findingId: string, a: string, b: string) {
    if (a === b) throw new ApiError("VALIDATION", "two reviewers cannot be the same actor", 400);
    this.reviewAssign.push({ findingId, reviewerId: a }, { findingId, reviewerId: b });
    this.persist(() => insertReviewAssignment(findingId, a));
    this.persist(() => insertReviewAssignment(findingId, b));
  }

  appeal(findingId: string, original: string, appealReviewer: string) {
    if (original === appealReviewer) throw new ApiError("VALIDATION", "appeal reviewer cannot be original", 400);
    const f = this.findings.get(findingId);
    if (!f) throw new ApiError("NOT_FOUND", "finding", 404);
    const man = [...this.manifests.values()].find((m) => m.sessionId === f.sessionId);
    if (man) {
      man.frozen = true;
      this.persist(() => freezeManifest(man.id));
    }
    const id = uuid();
    this.appeals.set(id, { id, findingId, original, appealReviewer });
    this.persist(() => upsertAppeal({ id, findingId, original, appealReviewer }));
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
    this.persist(() => upsertStaffAssignment({ orgId: exam.orgId, examId, userId, role }));
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
    if (man) {
      man.frozen = true;
      this.persist(() => freezeManifest(man.id));
    } else {
      this.manifests.set(sessionId, { id: sessionId, sessionId, frozen: true, body: {} });
      this.persist(() => upsertEvidenceManifest({ id: sessionId, sessionId, frozen: true, body: {} }));
    }
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
      this.recordAudit({ orgId: this.sessions.get(sessionId)?.orgId || "", action: "STOP_LIVE", payload: { sessionId } });
      return { stopped: true };
    }
    return { stopped: false, remaining: set.size };
  }

  startLive(sessionId: string, viewerId: string) {
    const set = this.liveViewers.get(sessionId) || new Set();
    set.add(viewerId);
    this.liveViewers.set(sessionId, set);
    this.recordAudit({ orgId: this.sessions.get(sessionId)?.orgId || "", action: "START_LIVE", payload: { sessionId, viewerId } });
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

  /** Fill memory maps from a durable snapshot (boot hydration). Memory stays the hot path. */
  loadSnapshot(snap: {
    orgs: { id: string; name: string; slug: string }[];
    users: { id: string; email: string; issuer: string; subject: string; name: string; passwordHash?: string }[];
    memberships: { orgId: string; userId: string }[];
    roles: { orgId: string; userId: string; role: Role; examId?: string }[];
    staffSessions: {
      id: string; orgId: string; userId: string; sessionHash: string; refreshHash: string;
      expires: number; revoked?: boolean; stepUpUntil?: number; csrf: string;
    }[];
    exams: { id: string; orgId: string; code: string; title: string; status: string; version: number; policyId?: string }[];
    policies: { id: string; examId: string; version: number; body: unknown; immutable: boolean }[];
    groups: { id: string; orgId: string; examId: string; name: string }[];
    enrollments: { id: string; orgId: string; examId: string; studentExternalId: string; displayName: string }[];
    tokens: { id: string; enrollmentId: string; hash: string; expires: number; redeemed?: boolean }[];
    sessions: {
      id: string; orgId: string; examId: string; enrollmentId: string;
      desired: string; observed: string; controlGen: number; connGen: number;
      connectivity: string; attention: string; claimOwner?: string;
    }[];
    attempts: { id: string; enrollmentId: string; terminal: boolean }[];
    cursors: { sessionId: string; acked: number }[];
    commands: {
      id: string; sessionId: string; type: string; idempotencyKey: string;
      status: string; result?: unknown; orgId: string;
    }[];
    findings: { id: string; sessionId: string; orgId: string; label: string; status: string; actorId?: string }[];
    revisions: { findingId: string; actorId: string; label: string }[];
    reviewAssign: { findingId: string; reviewerId: string }[];
    appeals: { id: string; findingId: string; original: string; appealReviewer?: string; outcome?: string }[];
    media: {
      id: string; orgId: string; sessionId: string; key: string; type: string;
      bytes: number; sha256: string; status: string; attempts: number;
    }[];
    manifests: { id: string; sessionId: string; frozen: boolean; body: unknown }[];
    staffAssignments: { examId: string; userId: string; role: string }[];
    streamTail: { examId: string; seq: number; payload: unknown }[];
    banks: { id: string; orgId: string; name: string }[];
    qgroups: { id: string; orgId: string; bankId: string; position: number; title: string; marks: number; negativeMarks: number; rubric: string }[];
    contentVersions: { id: string; orgId: string; bankId: string; version: number }[];
    variants: {
      id: string; orgId: string; groupId: string; contentVersionId?: string;
      position: number; stem: string; qtype: string; perQuestionS?: number; deprecated?: boolean;
    }[];
    qoptions: { id: string; orgId: string; variantId: string; position: number; label: string; correct: boolean }[];
    candidateCodes: { id: string; enrollmentId: string; hash: string; expires: number; redeemed?: boolean; uses: number; maxUses: number }[];
    candidateSessions: { id: string; sessionId: string; enrollmentId: string; hash: string; expires: number; revoked?: boolean; csrf: string }[];
    assignments: { sessionId: string; groupId: string; variantId: string; optionSeed: number; position: number }[];
    answers: { id: string; sessionId: string; variantId: string; optionIds: string[]; textAnswer: string; correct?: boolean; score?: number }[];
    devices: { id: string; enrollmentId: string; kind: "laptop" | "phone"; familyId: string; revoked?: boolean }[];
    refreshTokens: { hash: string; familyId: string; used?: boolean }[];
  }) {
    for (const o of snap.orgs) this.orgs.set(o.id, o);
    for (const u of snap.users) this.users.set(u.id, u);
    for (const m of snap.memberships) this.memberships.set(this.memKey(m.orgId, m.userId), m);
    for (const r of snap.roles) this.roles.push({ orgId: r.orgId, userId: r.userId, role: r.role, examId: r.examId });
    for (const s of snap.staffSessions) this.staffSessions.set(s.id, s);
    for (const e of snap.exams) this.exams.set(e.id, e);
    for (const p of snap.policies) this.policies.set(p.id, p);
    for (const g of snap.groups) this.groups.set(g.id, g);
    for (const e of snap.enrollments) this.enrollments.set(e.id, e);
    for (const t of snap.tokens) this.tokens.set(t.id, t);
    for (const s of snap.sessions) this.sessions.set(s.id, s);
    for (const a of snap.attempts) this.attempts.set(a.id, a);
    for (const c of snap.cursors) this.cursors.set(c.sessionId, c.acked);
    for (const c of snap.commands) this.commands.set(c.id, c);
    for (const f of snap.findings) this.findings.set(f.id, f);
    for (const r of snap.revisions) this.revisions.push(r);
    for (const r of snap.reviewAssign) this.reviewAssign.push(r);
    for (const a of snap.appeals) this.appeals.set(a.id, a);
    for (const m of snap.media) this.media.set(m.id, m);
    for (const m of snap.manifests) this.manifests.set(m.id, m);
    for (const a of snap.staffAssignments) this.staffAssignments.push(a);
    for (const r of snap.streamTail) this.examStream.push(r);
    for (const b of snap.banks) this.banks.set(b.id, b);
    for (const g of snap.qgroups) this.qgroups.set(g.id, g);
    for (const v of snap.contentVersions) this.contentVersions.set(v.id, v);
    for (const v of snap.variants) this.variants.set(v.id, v);
    for (const o of snap.qoptions) this.qoptions.set(o.id, o);
    for (const c of snap.candidateCodes) this.candidateCodes.set(c.id, c);
    for (const g of snap.candidateSessions) this.candidateSessions.set(g.id, g);
    for (const a of snap.assignments) this.assignments.set(`${a.sessionId}:${a.groupId}`, a);
    for (const a of snap.answers) this.answers.set(a.id, a);
    for (const d of snap.devices) {
      if (d.familyId) this.devices.set(d.id, d);
    }
    for (const r of snap.refreshTokens) this.refreshTokens.set(r.familyId, r);
  }

  /* ---------------- exam content: banks, groups, variants ---------------- */

  createBank(ctx: StaffContext, name: string) {
    this.require(ctx, "exam.write");
    const id = uuid();
    const bank = { id, orgId: ctx.orgId, name };
    this.banks.set(id, bank);
    this.persist(() => upsertBank(bank));
    return bank;
  }

  createGroup(ctx: StaffContext, bankId: string, input: { title: string; position?: number; marks?: number; negativeMarks?: number; rubric?: string }) {
    this.require(ctx, "exam.write");
    const bank = this.banks.get(bankId);
    if (!bank) throw new ApiError("NOT_FOUND", "bank", 404);
    this.assertOrg(ctx, bank.orgId);
    const id = uuid();
    const group = {
      id, orgId: ctx.orgId, bankId,
      position: input.position ?? [...this.qgroups.values()].filter((g) => g.bankId === bankId).length,
      title: input.title, marks: input.marks ?? 1, negativeMarks: input.negativeMarks ?? 0, rubric: input.rubric ?? "",
    };
    this.qgroups.set(id, group);
    this.persist(() => upsertGroup(group));
    return group;
  }

  createVariant(
    ctx: StaffContext,
    groupId: string,
    input: { stem: string; qtype?: string; perQuestionS?: number; position?: number; options: { label: string; correct?: boolean }[] },
  ) {
    this.require(ctx, "exam.write");
    const group = this.qgroups.get(groupId);
    if (!group) throw new ApiError("NOT_FOUND", "group", 404);
    this.assertOrg(ctx, group.orgId);
    if (!input.stem?.trim()) throw new ApiError("VALIDATION", "stem required", 400);
    if (!Array.isArray(input.options) || input.options.length < 2) throw new ApiError("VALIDATION", "at least 2 options", 400);
    const qtype = input.qtype ?? "mcq_single";
    if (qtype === "mcq_single" && input.options.filter((o) => o.correct).length !== 1) {
      throw new ApiError("VALIDATION", "mcq_single needs exactly one correct option", 400);
    }
    const id = uuid();
    const variant = {
      id, orgId: ctx.orgId, groupId,
      position: input.position ?? [...this.variants.values()].filter((v) => v.groupId === groupId).length,
      stem: input.stem, qtype, perQuestionS: input.perQuestionS,
    };
    this.variants.set(id, variant);
    const opts = input.options.map((o, i) => ({
      id: uuid(), orgId: ctx.orgId, variantId: id, position: i, label: o.label, correct: !!o.correct,
    }));
    for (const o of opts) this.qoptions.set(o.id, o);
    // Snapshot: publishBank mutates contentVersionId in place later; the queued
    // write must carry creation-time state or it can reference a version row
    // that does not exist yet (FK violation).
    const vSnap = structuredClone(variant);
    const oSnap = structuredClone(opts);
    this.persist(() => upsertVariantWithOptions(vSnap, oSnap));
    return { ...variant, options: opts.map((o) => ({ id: o.id, position: o.position, label: o.label })) };
  }

  deprecateVariant(ctx: StaffContext, variantId: string) {
    this.require(ctx, "exam.write");
    const variant = this.variants.get(variantId);
    if (!variant) throw new ApiError("NOT_FOUND", "variant", 404);
    this.assertOrg(ctx, variant.orgId);
    variant.deprecated = true;
    const vSnap = structuredClone(variant);
    this.persist(() => upsertVariantWithOptions(vSnap, []));
    return { id: variantId, deprecated: true };
  }

  publishBank(ctx: StaffContext, bankId: string) {
    this.require(ctx, "exam.write");
    const bank = this.banks.get(bankId);
    if (!bank) throw new ApiError("NOT_FOUND", "bank", 404);
    this.assertOrg(ctx, bank.orgId);
    const groups = [...this.qgroups.values()].filter((g) => g.bankId === bankId);
    if (groups.length === 0) throw new ApiError("VALIDATION", "bank has no groups", 400);
    for (const g of groups) {
      const live = [...this.variants.values()].filter((v) => v.groupId === g.id && !v.deprecated);
      if (live.length === 0) throw new ApiError("VALIDATION", `group has no live variants: ${g.title}`, 400);
    }
    const version = Math.max(0, ...[...this.contentVersions.values()].filter((v) => v.bankId === bankId).map((v) => v.version)) + 1;
    const id = uuid();
    const ver = { id, orgId: ctx.orgId, bankId, version };
    this.contentVersions.set(id, ver);
    // Atomic publish: version row + variant stamping in ONE transaction (no FK race).
    const stamped: string[] = [];
    for (const v of this.variants.values()) {
      const g = this.qgroups.get(v.groupId);
      if (g?.bankId === bankId && !v.contentVersionId && !v.deprecated) {
        v.contentVersionId = id;
        stamped.push(v.id);
      }
    }
    this.persist(() => publishContentVersion(ver, stamped));
    return ver;
  }

  bindExamContent(ctx: StaffContext, examId: string, input: { contentVersionId: string; allowBackNavigation?: boolean; durationS?: number }) {
    this.require(ctx, "exam.write");
    const exam = this.exams.get(examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.assertOrg(ctx, exam.orgId);
    const ver = this.contentVersions.get(input.contentVersionId);
    if (!ver) throw new ApiError("NOT_FOUND", "content version", 404);
    if (ver.orgId !== exam.orgId) throw new ApiError("TENANT_DENIED", "cross-tenant content", 403);
    exam.contentVersionId = ver.id;
    exam.allowBackNavigation = !!input.allowBackNavigation;
    exam.durationS = input.durationS;
    this.persist(() => upsertExamContent(exam.orgId, examId, {
      contentVersionId: ver.id, allowBackNavigation: exam.allowBackNavigation, durationS: exam.durationS,
    }));
    return { exam_id: examId, content_version_id: ver.id, allow_back_navigation: exam.allowBackNavigation, duration_s: exam.durationS ?? null };
  }

  /* ---------------- candidate access: codes, grants, items, answers ---------------- */

  issueCandidateCode(ctx: StaffContext, enrollmentId: string) {
    this.require(ctx, "roster.import");
    const en = this.enrollments.get(enrollmentId);
    if (!en) throw new ApiError("NOT_FOUND", "enrollment", 404);
    this.assertOrg(ctx, en.orgId);
    const raw = randomBytes(6).toString("hex").toUpperCase();
    const id = uuid();
    const rec = { id, enrollmentId, hash: pepperHash(raw, this.pepper), expires: nowPlus(30 * 86400_000), uses: 0, maxUses: 3 };
    this.candidateCodes.set(id, rec);
    this.persist(() => upsertCandidateCode({ id, enrollmentId, codeHash: rec.hash, expiresAt: rec.expires, maxUses: rec.maxUses }));
    return { id, code: raw, enrollment_id: enrollmentId };
  }

  candidateCodeStatus(ctx: StaffContext, enrollmentId: string) {
    this.require(ctx, "roster.import");
    const en = this.enrollments.get(enrollmentId);
    if (!en) throw new ApiError("NOT_FOUND", "enrollment", 404);
    this.assertOrg(ctx, en.orgId);
    return [...this.candidateCodes.values()]
      .filter((c) => c.enrollmentId === enrollmentId)
      .map((c) => ({ id: c.id, redeemed: !!c.redeemed, uses: c.uses, max_uses: c.maxUses, expires_at: new Date(c.expires).toISOString() }));
  }

  redeemCandidateCode(code: string) {
    const normalized = code.trim().toUpperCase();
    const rec = [...this.candidateCodes.values()].find((c) => hashEqual(c.hash, pepperHash(normalized, this.pepper)));
    if (!rec) throw new ApiError("AUTH_DENIED", "bad code", 401);
    if (rec.uses >= rec.maxUses) throw new ApiError("AUTH_DENIED", "code exhausted", 401);
    if (Date.now() > rec.expires) throw new ApiError("AUTH_DENIED", "code expired", 401);
    rec.uses += 1;
    if (rec.uses >= rec.maxUses) rec.redeemed = true;
    const en = this.enrollments.get(rec.enrollmentId);
    if (!en) throw new ApiError("NOT_FOUND", "enrollment", 404);
    const exam = this.exams.get(en.examId);
    if (!exam) throw new ApiError("NOT_FOUND", "exam", 404);
    this.persist(() => upsertCandidateCode({
      id: rec.id, enrollmentId: rec.enrollmentId, codeHash: rec.hash,
      expiresAt: rec.expires, maxUses: rec.maxUses, uses: rec.uses, redeemed: rec.redeemed,
    }));
    let session = [...this.sessions.values()].find((s) => s.enrollmentId === en.id);
    if (!session) {
      const sid = uuid();
      session = {
        id: sid, orgId: en.orgId, examId: en.examId, enrollmentId: en.id,
        desired: "READY", observed: "READY", controlGen: 0, connGen: 0,
        connectivity: "offline", attention: "unknown",
      };
      this.sessions.set(sid, session);
      this.attempts.set(sid, { enrollmentId: en.id, terminal: false });
      this.cursors.set(sid, 0);
      const createdSession = session;
      this.persist(() => upsertSession(createdSession));
      this.persist(() => insertSessionAttempt({ id: sid, sessionId: sid, enrollmentId: en.id, terminal: false }));
    }
    const raw = randomBytes(32).toString("hex");
    const grantId = uuid();
    const grant = { id: grantId, sessionId: session.id, enrollmentId: en.id, hash: pepperHash(raw, this.pepper), expires: nowPlus(12 * 3600_000), csrf: randomBytes(16).toString("hex") };
    this.candidateSessions.set(grantId, grant);
    this.persist(() => upsertCandidateSession({ id: grantId, sessionId: session.id, enrollmentId: en.id, tokenHash: grant.hash, expiresAt: grant.expires, csrf: grant.csrf }));
    return { grant: raw, csrf: grant.csrf, session_id: session.id, exam: { id: exam.id, code: exam.code, title: exam.title } };
  }

  candidateFromGrant(raw: string): { sessionId: string; enrollmentId: string; csrf: string } {
    const rec = [...this.candidateSessions.values()].find((g) => !g.revoked && hashEqual(g.hash, pepperHash(raw, this.pepper)));
    if (!rec) throw new ApiError("AUTH_DENIED", "bad grant", 401);
    if (Date.now() > rec.expires) throw new ApiError("AUTH_DENIED", "grant expired", 401);
    return { sessionId: rec.sessionId, enrollmentId: rec.enrollmentId, csrf: rec.csrf };
  }

  /** Seeded draw: one live variant per group + per-question option permutation seed. */
  private drawAssignments(sessionId: string) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const exam = this.exams.get(session.examId) as { contentVersionId?: string } | undefined;
    if (!exam?.contentVersionId) throw new ApiError("CONFLICT", "exam has no published content", 409);
    const groups = [...this.qgroups.values()]
      .filter((g) => [...this.contentVersions.values()].some((v) => v.id === exam.contentVersionId && v.bankId === g.bankId))
      .sort((a, b) => a.position - b.position);
    let pos = 0;
    for (const g of groups) {
      const key = `${sessionId}:${g.id}`;
      if (this.assignments.has(key)) continue;
      const live = [...this.variants.values()].filter(
        (v) => v.groupId === g.id && v.contentVersionId === exam.contentVersionId && !v.deprecated,
      );
      if (live.length === 0) throw new ApiError("CONFLICT", `no live variant for group ${g.title}`, 409);
      const seedBase = parseInt(createHash("sha256").update(`${sessionId}:${g.id}`).digest("hex").slice(0, 8), 16);
      const variant = live[seedBase % live.length];
      const optionSeed = parseInt(createHash("sha256").update(`opts:${sessionId}:${variant.id}`).digest("hex").slice(0, 12), 16);
      const rec = { sessionId, groupId: g.id, variantId: variant.id, optionSeed, position: pos++ };
      this.assignments.set(key, rec);
      this.persist(() => upsertAssignment(rec));
    }
  }

  private shuffledOptions(variantId: string, seed: number) {
    const opts = [...this.qoptions.values()].filter((o) => o.variantId === variantId).sort((a, b) => a.position - b.position);
    let s = seed % 2147483647;
    if (s <= 0) s += 2147483646;
    const rand = () => (s = (s * 16807) % 2147483647) / 2147483647;
    const arr = [...opts];
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  nextItem(sessionId: string) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    if (session.desired === "ENDED" || session.observed === "ENDED") throw new ApiError("CONFLICT", "exam ended", 409);
    this.drawAssignments(sessionId);
    const exam = this.exams.get(session.examId) as {
      contentVersionId?: string; allowBackNavigation?: boolean; durationS?: number;
    } | undefined;
    const ordered = [...this.assignments.values()].filter((a) => a.sessionId === sessionId).sort((a, b) => a.position - b.position);
    const answered = new Set(
      [...this.answers.values()].filter((a) => a.sessionId === sessionId).map((a) => a.variantId),
    );
    const next = ordered.find((a) => !answered.has(a.variantId));
    if (!next) return { done: true, total: ordered.length, answered: answered.size };
    const variant = this.variants.get(next.variantId)!;
    const group = this.qgroups.get(next.groupId)!;
    return {
      done: false,
      position: next.position + 1,
      total: ordered.length,
      answered: answered.size,
      variant_id: variant.id,
      group_title: group.title,
      stem: variant.stem,
      qtype: variant.qtype,
      per_question_s: variant.perQuestionS ?? null,
      allow_back_navigation: !!exam?.allowBackNavigation,
      options: this.shuffledOptions(variant.id, next.optionSeed).map((o) => ({ id: o.id, label: o.label })),
    };
  }

  submitAnswer(sessionId: string, variantId: string, optionIds: string[], textAnswer: string) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    if (session.desired === "ENDED" || session.observed === "ENDED") throw new ApiError("CONFLICT", "exam ended", 409);
    const exam = this.exams.get(session.examId) as {
      contentVersionId?: string; allowBackNavigation?: boolean;
    } | undefined;
    const assignment = [...this.assignments.values()].find((a) => a.sessionId === sessionId && a.variantId === variantId);
    if (!assignment) throw new ApiError("VALIDATION", "item not assigned to this session", 403);
    const variant = this.variants.get(variantId)!;
    const group = this.qgroups.get(assignment.groupId)!;
    const existing = [...this.answers.values()].find((a) => a.sessionId === sessionId && a.variantId === variantId);
    if (existing && !exam?.allowBackNavigation) throw new ApiError("CONFLICT", "already answered", 409);
    const validOptionIds = new Set([...this.qoptions.values()].filter((o) => o.variantId === variantId).map((o) => o.id));
    const picked = [...new Set(optionIds)].filter((id) => validOptionIds.has(id));
    let correct: boolean | undefined;
    let score: number | undefined;
    if (variant.qtype === "mcq_single" || variant.qtype === "mcq_multi") {
      const truth = new Set(
        [...this.qoptions.values()].filter((o) => o.variantId === variantId && o.correct).map((o) => o.id),
      );
      correct = picked.length === truth.size && picked.every((id) => truth.has(id));
      score = correct ? group.marks : -group.negativeMarks;
    }
    const rec = {
      id: uuid(), sessionId, variantId, optionIds: picked, textAnswer: textAnswer || "",
      correct, score,
    };
    if (existing) {
      Object.assign(existing, { optionIds: picked, textAnswer: textAnswer || "", correct, score });
    } else {
      this.answers.set(rec.id, rec);
    }
    const stored = existing ?? rec;
    this.persist(() => upsertAnswer({
      id: stored.id, sessionId, variantId, optionIds: picked,
      textAnswer: textAnswer || "", correct, score,
    }));
    try {
      const seq = (this.cursors.get(sessionId) || 0) + 1;
      const batchId = uuid();
      const payload = { type: "ANSWER", variant_id: variantId, group_id: assignment.groupId, correct: correct ?? null };
      const hash = createHash("sha256").update(JSON.stringify(payload)).digest("hex");
      this.ingestEvent(sessionId, seq, batchId, hash, payload);
    } catch {
      // answer is durable in candidate_answer; event ordering conflicts must not void it
    }
    return { accepted: true };
  }

  candidateStatus(sessionId: string) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    const ordered = [...this.assignments.values()].filter((a) => a.sessionId === sessionId);
    const answered = [...this.answers.values()].filter((a) => a.sessionId === sessionId).length;
    return { session_id: sessionId, total: ordered.length, answered, done: ordered.length > 0 && answered >= ordered.length };
  }

  sessionAnswers(ctx: StaffContext, sessionId: string) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new ApiError("NOT_FOUND", "session", 404);
    this.assertOrg(ctx, session.orgId);
    this.require(ctx, "session.read");
    return [...this.answers.values()]
      .filter((a) => a.sessionId === sessionId)
      .map((a) => {
        const variant = this.variants.get(a.variantId);
        const truth = [...this.qoptions.values()].filter((o) => o.variantId === a.variantId && o.correct).map((o) => o.id);
        return { ...a, stem: variant?.stem, qtype: variant?.qtype, correct_option_ids: truth };
      });
  }

  /** Worker sweep: end sessions whose exam window or duration expired. */
  endExpiredSessions(now = Date.now()) {
    const ended: string[] = [];
    for (const session of this.sessions.values()) {
      if (session.desired === "ENDED" || session.observed === "ENDED") continue;
      const exam = this.exams.get(session.examId);
      if (!exam) continue;
      let deadline: number | null = null;
      if (typeof exam.durationS === "number" && session.startedAt) {
        deadline = session.startedAt + exam.durationS * 1000;
      }
      if (deadline !== null && now >= deadline) {
        session.desired = "ENDED";
        session.controlGen += 1;
        const id = uuid();
        const cmd = { id, sessionId: session.id, type: "EXAM_END", idempotencyKey: `expiry:${session.id}`, status: "accepted", orgId: session.orgId };
        this.commands.set(id, cmd);
        this.appendStream(session.examId, { op: "upsert", session_id: session.id, patch: { desired: "ENDED", reason: "time_expired" } });
        this.recordAudit({ orgId: session.orgId, action: "command:EXAM_END", payload: { sessionId: session.id, id, reason: "time_expired" } });
        this.persist(async () => {
          await upsertSession(session);
          await upsertCommand({ ...cmd, body: { reason: "time_expired" } });
        });
        ended.push(session.id);
      }
    }
    return { ended };
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
// No auto-seed: demo data is provisioned explicitly via SEED_DEMO (see api/gateway/worker).
