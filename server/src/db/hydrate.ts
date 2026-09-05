import { getPool } from "./pool.js";
import { createLogger } from "../log.js";
import type { Role } from "../store.js";

const log = createLogger("hydrate");

/** Durable snapshot loaded from Postgres on boot. High-volume event payloads stay in SQL. */
export interface HydratedSnapshot {
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
  staffAssignments: { examId: string; userId: string; role: string; orgId: string }[];
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
}

const empty: HydratedSnapshot = {
  orgs: [], users: [], memberships: [], roles: [], staffSessions: [],
  exams: [], policies: [], groups: [], enrollments: [], tokens: [],
  sessions: [], attempts: [], cursors: [], commands: [],
  findings: [], revisions: [], reviewAssign: [], appeals: [],
  media: [], manifests: [], staffAssignments: [], streamTail: [],
  banks: [], qgroups: [], contentVersions: [], variants: [], qoptions: [],
  candidateCodes: [], candidateSessions: [], assignments: [], answers: [],
  devices: [], refreshTokens: [],
};

const toMs = (v: unknown): number => (v instanceof Date ? v.getTime() : Number(v ?? 0));

/** Load durable state. Returns empty snapshot when DATABASE_URL is unset. */
export async function hydrate(): Promise<HydratedSnapshot> {
  const pool = getPool();
  if (!pool) return structuredClone(empty);
  const snap: HydratedSnapshot = structuredClone(empty);
  try {
    const orgs = await pool.query(`SELECT id, name, slug FROM organization`);
    snap.orgs = orgs.rows.map((r) => ({ id: r.id, name: r.name, slug: r.slug }));

    const users = await pool.query(
      `SELECT id, email_normalized AS email, issuer, subject, display_name AS name,
              password_hash AS "passwordHash" FROM user_account`,
    );
    snap.users = users.rows.map((r) => ({
      id: r.id, email: r.email, issuer: r.issuer, subject: r.subject, name: r.name,
      passwordHash: r.passwordHash ?? undefined,
    }));

    const mems = await pool.query(`SELECT org_id AS "orgId", user_id AS "userId" FROM organization_membership WHERE status = 'active'`);
    snap.memberships = mems.rows;

    const roles = await pool.query(
      `SELECT org_id AS "orgId", user_id AS "userId", role FROM org_role_assignment`,
    );
    snap.roles = roles.rows.map((r) => ({ orgId: r.orgId as string, userId: r.userId as string, role: r.role as Role }));

    const sess = await pool.query(
      `SELECT id, org_id AS "orgId", user_id AS "userId", session_hash AS "sessionHash",
              refresh_hash AS "refreshHash", expires_at AS "expiresAt",
              revoked_at AS "revokedAt", step_up_until AS "stepUpUntil", csrf_secret AS "csrf"
       FROM staff_auth_session WHERE revoked_at IS NULL`,
    );
    snap.staffSessions = sess.rows
      .map((r) => ({
        id: r.id, orgId: r.orgId, userId: r.userId,
        sessionHash: r.sessionHash, refreshHash: r.refreshHash,
        expires: toMs(r.expiresAt), revoked: false as boolean | undefined,
        stepUpUntil: r.stepUpUntil ? toMs(r.stepUpUntil) : undefined, csrf: r.csrf,
      }))
      .filter((s) => s.expires > Date.now());

    const exams = await pool.query(
      `SELECT id, org_id AS "orgId", code, title, status, version,
              content_version_id AS "contentVersionId",
              allow_back_navigation AS "allowBackNavigation", duration_s AS "durationS" FROM exam`,
    );
    snap.exams = exams.rows.map((r) => ({
      id: r.id, orgId: r.orgId, code: r.code, title: r.title, status: r.status, version: r.version,
      contentVersionId: r.contentVersionId ?? undefined,
      allowBackNavigation: !!r.allowBackNavigation,
      durationS: r.durationS ?? undefined,
    }));

    const policies = await pool.query(
      `SELECT id, exam_id AS "examId", version, body, immutable FROM policy_version`,
    );
    snap.policies = policies.rows.map((r) => ({
      id: r.id, examId: r.examId, version: r.version, body: r.body, immutable: r.immutable,
    }));
    for (const exam of snap.exams) {
      const latest = snap.policies.filter((p) => p.examId === exam.id).sort((a, b) => b.version - a.version)[0];
      if (latest) exam.policyId = latest.id;
    }

    const groups = await pool.query(`SELECT id, org_id AS "orgId", exam_id AS "examId", name FROM candidate_group`);
    snap.groups = groups.rows;

    const enrollments = await pool.query(
      `SELECT id, org_id AS "orgId", exam_id AS "examId",
              student_external_id AS "studentExternalId", display_name AS "displayName" FROM enrollment`,
    );
    snap.enrollments = enrollments.rows;

    const tokens = await pool.query(
      `SELECT id, enrollment_id AS "enrollmentId", token_hash AS "hash", expires_at AS "expiresAt",
              redeemed_at AS "redeemedAt" FROM enrollment_token`,
    );
    snap.tokens = tokens.rows
      .map((r) => ({ id: r.id, enrollmentId: r.enrollmentId, hash: r.hash, expires: toMs(r.expiresAt), redeemed: !!r.redeemedAt }))
      .filter((t) => !t.redeemed && t.expires > Date.now());

    const sessions = await pool.query(
      `SELECT id, org_id AS "orgId", exam_id AS "examId", enrollment_id AS "enrollmentId",
              desired_lifecycle_state AS "desired", observed_lifecycle_state AS "observed",
              control_generation AS "controlGen", connection_generation AS "connGen",
              connectivity, attention, started_at AS "startedAt" FROM session`,
    );
    snap.sessions = sessions.rows.map((r) => ({
      ...r, startedAt: r.startedAt ? toMs(r.startedAt) : undefined,
    }));

    const attempts = await pool.query(`SELECT id, enrollment_id AS "enrollmentId", terminal FROM session_attempt`);
    snap.attempts = attempts.rows.map((r) => ({ id: r.id, enrollmentId: r.enrollmentId, terminal: r.terminal }));

    const cursors = await pool.query(`SELECT session_id AS "sessionId", acked_through AS "acked" FROM ingest_cursor`);
    snap.cursors = cursors.rows;

    const commands = await pool.query(
      `SELECT id, session_id AS "sessionId", command_type AS "type", idempotency_key AS "idempotencyKey",
              status, result, org_id AS "orgId" FROM command`,
    );
    snap.commands = commands.rows;

    const findings = await pool.query(
      `SELECT id, session_id AS "sessionId", org_id AS "orgId", event_seq AS "eventSeq",
              label, status, actor_id AS "actorId" FROM finding`,
    );
    snap.findings = findings.rows.map((r) => ({
      id: r.id, sessionId: r.sessionId, orgId: r.orgId, label: r.label, status: r.status, actorId: r.actorId ?? undefined,
    }));

    const revisions = await pool.query(`SELECT finding_id AS "findingId", actor_id AS "actorId", label FROM label_revision ORDER BY id`);
    snap.revisions = revisions.rows;

    const reviewAssign = await pool.query(`SELECT finding_id AS "findingId", reviewer_id AS "reviewerId" FROM review_assignment`);
    snap.reviewAssign = reviewAssign.rows;

    const appeals = await pool.query(
      `SELECT id, finding_id AS "findingId", original_reviewer_id AS "original",
              appeal_reviewer_id AS "appealReviewer", outcome FROM appeal`,
    );
    snap.appeals = appeals.rows.map((r) => ({
      id: r.id, findingId: r.findingId, original: r.original ?? "", appealReviewer: r.appealReviewer ?? undefined,
      outcome: r.outcome ?? undefined,
    }));

    const media = await pool.query(
      `SELECT id, org_id AS "orgId", session_id AS "sessionId", object_key AS "key",
              content_type AS "type", bytes, sha256, status FROM media_asset`,
    );
    snap.media = media.rows.map((r) => ({ ...r, attempts: 0 }));

    const manifests = await pool.query(`SELECT id, session_id AS "sessionId", frozen, body FROM evidence_manifest`);
    snap.manifests = manifests.rows.map((r) => ({ id: r.id, sessionId: r.sessionId, frozen: r.frozen, body: r.body }));

    const staffAssign = await pool.query(
      `SELECT org_id AS "orgId", exam_id AS "examId", user_id AS "userId", role FROM exam_staff_assignment`,
    );
    snap.staffAssignments = staffAssign.rows;

    const stream = await pool.query(
      `SELECT exam_id AS "examId", stream_seq AS "seq", payload FROM (
         SELECT *, row_number() OVER (PARTITION BY exam_id ORDER BY stream_seq DESC) AS rn FROM exam_stream
       ) t WHERE rn <= 200 ORDER BY exam_id, stream_seq`,
    );
    snap.streamTail = stream.rows;

    const banks = await pool.query(`SELECT id, org_id AS "orgId", name FROM question_bank`);
    snap.banks = banks.rows;

    const qgroups = await pool.query(
      `SELECT id, org_id AS "orgId", bank_id AS "bankId", position, title,
              marks, negative_marks AS "negativeMarks", rubric FROM question_group ORDER BY position`,
    );
    snap.qgroups = qgroups.rows.map((r) => ({ ...r, marks: Number(r.marks), negativeMarks: Number(r.negativeMarks) }));

    const versions = await pool.query(
      `SELECT id, org_id AS "orgId", bank_id AS "bankId", version FROM content_version`,
    );
    snap.contentVersions = versions.rows;

    const variants = await pool.query(
      `SELECT id, org_id AS "orgId", group_id AS "groupId", content_version_id AS "contentVersionId",
              position, stem, qtype, per_question_s AS "perQuestionS", deprecated FROM question_variant`,
    );
    snap.variants = variants.rows.map((r) => ({
      id: r.id, orgId: r.orgId, groupId: r.groupId, contentVersionId: r.contentVersionId ?? undefined,
      position: r.position, stem: r.stem, qtype: r.qtype,
      perQuestionS: r.perQuestionS ?? undefined, deprecated: !!r.deprecated,
    }));

    const qoptions = await pool.query(
      `SELECT id, org_id AS "orgId", variant_id AS "variantId", position, label, correct FROM question_option`,
    );
    snap.qoptions = qoptions.rows.map((r) => ({ ...r, correct: !!r.correct }));

    const codes = await pool.query(
      `SELECT id, enrollment_id AS "enrollmentId", code_hash AS "hash",
              expires_at AS "expiresAt", redeemed_at AS "redeemedAt", max_uses AS "maxUses", uses
       FROM candidate_login_code`,
    );
    snap.candidateCodes = codes.rows
      .map((r) => ({
        id: r.id, enrollmentId: r.enrollmentId, hash: r.hash, expires: toMs(r.expiresAt),
        redeemed: !!r.redeemedAt, uses: r.uses, maxUses: r.maxUses,
      }))
      .filter((c) => !c.redeemed && c.expires > Date.now());

    const grants = await pool.query(
      `SELECT id, session_id AS "sessionId", enrollment_id AS "enrollmentId",
              token_hash AS "hash", csrf_secret AS "csrf", expires_at AS "expiresAt",
              revoked_at AS "revokedAt" FROM candidate_session WHERE revoked_at IS NULL`,
    );
    snap.candidateSessions = grants.rows
      .map((r) => ({
        id: r.id, sessionId: r.sessionId, enrollmentId: r.enrollmentId, hash: r.hash,
        expires: toMs(r.expiresAt), revoked: false as boolean | undefined, csrf: r.csrf || undefined as unknown as string,
      }))
      .filter((g) => g.expires > Date.now() && g.csrf);

    const assignments = await pool.query(
      `SELECT session_id AS "sessionId", group_id AS "groupId", variant_id AS "variantId",
              option_seed AS "optionSeed", position FROM candidate_item_assignment`,
    );
    snap.assignments = assignments.rows.map((r) => ({ ...r, optionSeed: Number(r.optionSeed) }));

    const answers = await pool.query(
      `SELECT id, session_id AS "sessionId", variant_id AS "variantId",
              option_ids AS "optionIds", text_answer AS "textAnswer", correct, score FROM candidate_answer`,
    );
    snap.answers = answers.rows.map((r) => ({
      id: r.id, sessionId: r.sessionId, variantId: r.variantId, optionIds: r.optionIds ?? [],
      textAnswer: r.textAnswer ?? "", correct: r.correct ?? undefined,
      score: r.score === null || r.score === undefined ? undefined : Number(r.score),
    }));

    const devices = await pool.query(`SELECT id, enrollment_id AS "enrollmentId", kind FROM device`);
    const families = await pool.query(`SELECT id, device_id AS "deviceId", revoked_at AS "revokedAt" FROM device_credential_family`);
    const familyByDevice = new Map(families.rows.map((f: { deviceId: string; id: string; revokedAt: unknown }) => [f.deviceId, f]));
    snap.devices = devices.rows.map((d) => {
      const fam = familyByDevice.get(d.id) as { id: string; revokedAt: unknown } | undefined;
      return {
        id: d.id, enrollmentId: d.enrollmentId, kind: d.kind,
        familyId: fam?.id ?? "", revoked: !!fam?.revokedAt,
      };
    });

    const refresh = await pool.query(`SELECT family_id AS "familyId", token_hash AS "hash", used_at AS "usedAt" FROM device_refresh_token`);
    const currentByFamily = new Map<string, { hash: string; familyId: string; used?: boolean }>();
    for (const row of refresh.rows) {
      const rec = { hash: row.hash as string, familyId: row.familyId as string, used: !!row.usedAt };
      const prev = currentByFamily.get(rec.familyId);
      if (!prev || (!rec.used && prev.used)) currentByFamily.set(rec.familyId, rec);
    }
    snap.refreshTokens = [...currentByFamily.values()];
  } catch (err) {
    log.warn({ err }, "hydrate failed; starting with empty memory state");
    return structuredClone(empty);
  }
  return snap;
}
