import type { PoolClient } from "pg";
import { createLogger } from "../log.js";
import { getPool } from "./pool.js";
import { withTransaction } from "./transaction.js";

const log = createLogger("persist");

let lastStatus: "ok" | "down" | "memory" = process.env.DATABASE_URL ? "down" : "memory";
let persistChain: Promise<void> = Promise.resolve();

export type PostgresHealth = "ok" | "down" | "memory";

export function postgresStatus(): PostgresHealth {
  if (!process.env.DATABASE_URL) return "memory";
  return lastStatus === "memory" ? "down" : lastStatus;
}

export async function ping(): Promise<PostgresHealth> {
  if (!process.env.DATABASE_URL) {
    lastStatus = "memory";
    return lastStatus;
  }
  const pool = getPool();
  if (!pool) {
    lastStatus = "down";
    return lastStatus;
  }
  try {
    await pool.query("SELECT 1");
    lastStatus = "ok";
    return lastStatus;
  } catch {
    lastStatus = "down";
    return lastStatus;
  }
}

/** Fire-and-forget persist; no-op unless DATABASE_URL is set and a pool exists. */
export function enqueuePersist(work: () => Promise<void>): void {
  if (!process.env.DATABASE_URL) return;
  if (!getPool()) return;
  persistChain = persistChain
    .then(work)
    .catch((err: unknown) => {
      log.warn({ err }, "postgres persist failed");
    });
}

export function flushPersist(): Promise<void> {
  return persistChain;
}

async function withOrg<T>(orgId: string, fn: (client: PoolClient) => Promise<T>): Promise<T | undefined> {
  const pool = getPool();
  if (!pool) return undefined;
  const client = await pool.connect();
  try {
    return await withTransaction(client, async (c) => {
      await c.query("SELECT set_config('app.org_id', $1, true)", [orgId]);
      return fn(c);
    });
  } finally {
    try {
      await client.query("RESET app.org_id");
    } catch {
      // connection may already be broken
    }
    client.release();
  }
}

export async function upsertOrganization(row: { id: string; name: string; slug: string }): Promise<void> {
  await withOrg(row.id, async (c) => {
    await c.query(
      `INSERT INTO organization (id, name, slug)
       VALUES ($1, $2, $3)
       ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug`,
      [row.id, row.name, row.slug],
    );
  });
}

export async function upsertExam(
  exam: { id: string; orgId: string; code: string; title: string; status: string; version: number },
  policy?: { id: string; examId: string; version: number; body: unknown; immutable: boolean },
): Promise<void> {
  await withOrg(exam.orgId, async (c) => {
    await c.query(
      `INSERT INTO exam (id, org_id, code, title, status, version)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (id) DO UPDATE SET
         title = EXCLUDED.title,
         status = EXCLUDED.status,
         version = EXCLUDED.version`,
      [exam.id, exam.orgId, exam.code, exam.title, exam.status, exam.version],
    );
    if (policy) {
      await c.query(
        `INSERT INTO policy_version (id, org_id, exam_id, version, body, immutable)
         VALUES ($1, $2, $3, $4, $5::jsonb, $6)
         ON CONFLICT (id) DO UPDATE SET
           body = EXCLUDED.body,
           immutable = EXCLUDED.immutable`,
        [policy.id, exam.orgId, policy.examId, policy.version, JSON.stringify(policy.body ?? {}), policy.immutable],
      );
    }
  });
}

export async function upsertEnrollment(row: {
  id: string;
  orgId: string;
  examId: string;
  studentExternalId: string;
  displayName: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO enrollment (id, org_id, exam_id, student_external_id, display_name)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name`,
      [row.id, row.orgId, row.examId, row.studentExternalId, row.displayName],
    );
  });
}

export async function upsertSession(row: {
  id: string;
  orgId: string;
  examId: string;
  enrollmentId: string;
  desired: string;
  observed: string;
  controlGen: number;
  connGen: number;
  connectivity: string;
  attention: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO session (
         id, org_id, exam_id, enrollment_id,
         desired_lifecycle_state, observed_lifecycle_state,
         control_generation, connection_generation, connectivity, attention, started_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
       ON CONFLICT (id) DO UPDATE SET
         desired_lifecycle_state = EXCLUDED.desired_lifecycle_state,
         observed_lifecycle_state = EXCLUDED.observed_lifecycle_state,
         control_generation = EXCLUDED.control_generation,
         connection_generation = EXCLUDED.connection_generation,
         connectivity = EXCLUDED.connectivity,
         attention = EXCLUDED.attention,
         started_at = COALESCE(EXCLUDED.started_at, session.started_at)`,
      [
        row.id,
        row.orgId,
        row.examId,
        row.enrollmentId,
        row.desired,
        row.observed,
        row.controlGen,
        row.connGen,
        row.connectivity,
        row.attention,
        (row as { startedAt?: number }).startedAt ? new Date((row as { startedAt?: number }).startedAt!).toISOString() : null,
      ],
    );
  });
}

export async function upsertEvent(row: {
  sessionId: string;
  seq: number;
  batchId: string;
  hash: string;
  payload: unknown;
  orgId: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO event (org_id, session_id, seq_no, batch_id, payload_hash, payload)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)
       ON CONFLICT DO NOTHING`,
      [row.orgId, row.sessionId, row.seq, row.batchId, row.hash, JSON.stringify(row.payload ?? {})],
    );
  });
}

export async function upsertCommand(row: {
  id: string;
  sessionId: string;
  type: string;
  idempotencyKey: string;
  status: string;
  result?: unknown;
  orgId: string;
  body?: unknown;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO command (id, org_id, session_id, command_type, idempotency_key, body, status, result)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::jsonb)
       ON CONFLICT (id) DO UPDATE SET
         status = EXCLUDED.status,
         result = EXCLUDED.result`,
      [
        row.id,
        row.orgId,
        row.sessionId,
        row.type,
        row.idempotencyKey,
        JSON.stringify(row.body ?? {}),
        row.status,
        row.result === undefined ? null : JSON.stringify(row.result),
      ],
    );
  });
}

/* ---------------- identity / tenancy ---------------- */

export async function upsertUserAccount(row: {
  id: string;
  email: string;
  issuer: string;
  subject: string;
  name: string;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO user_account (id, email_normalized, issuer, subject, display_name)
     VALUES ($1, $2, $3, $4, $5)
     ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name`,
    [row.id, row.email.toLowerCase(), row.issuer, row.subject, row.name],
  );
}

export async function upsertMembership(orgId: string, userId: string): Promise<void> {
  await withOrg(orgId, async (c) => {
    await c.query(
      `INSERT INTO organization_membership (org_id, user_id, status)
       VALUES ($1, $2, 'active')
       ON CONFLICT (org_id, user_id) DO UPDATE SET status = 'active'`,
      [orgId, userId],
    );
  });
}

export async function upsertRoleAssignment(row: {
  orgId: string;
  userId: string;
  role: string;
  examId?: string;
  groupId?: string;
}): Promise<void> {
  const zero = "00000000-0000-0000-0000-000000000000";
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO org_role_assignment (org_id, user_id, role, exam_id, group_id)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT DO NOTHING`,
      [row.orgId, row.userId, row.role, row.examId ?? zero, row.groupId ?? zero],
    );
  });
}

export async function upsertStaffSession(row: {
  id: string;
  orgId: string;
  userId: string;
  sessionHash: string;
  refreshHash: string;
  expiresAt: number;
  revoked?: boolean;
  stepUpUntil?: number;
  csrf: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO staff_auth_session
         (id, org_id, user_id, session_hash, refresh_hash, expires_at, revoked_at, step_up_until, csrf_secret)
       VALUES ($1, $2, $3, $4, $5, to_timestamp($6 / 1000.0), $7, $8, $9)
       ON CONFLICT (id) DO UPDATE SET
         revoked_at = EXCLUDED.revoked_at,
         step_up_until = EXCLUDED.step_up_until`,
      [
        row.id,
        row.orgId,
        row.userId,
        row.sessionHash,
        row.refreshHash,
        row.expiresAt,
        row.revoked ? new Date().toISOString() : null,
        row.stepUpUntil ? new Date(row.stepUpUntil).toISOString() : null,
        row.csrf,
      ],
    );
  });
}

export async function insertAudit(row: {
  orgId: string;
  actorId?: string;
  action: string;
  payload: unknown;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO audit_action (org_id, actor_id, action, payload)
       VALUES ($1, $2, $3, $4::jsonb)`,
      [row.orgId, row.actorId ?? null, row.action, JSON.stringify(row.payload ?? {})],
    );
  });
}

/* ---------------- exam topology ---------------- */

export async function upsertCandidateGroup(row: { id: string; orgId: string; examId: string; name: string }): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO candidate_group (id, org_id, exam_id, name)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name`,
      [row.id, row.orgId, row.examId, row.name],
    );
  });
}

export async function upsertStaffAssignment(row: {
  orgId: string;
  examId: string;
  userId: string;
  role: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO exam_staff_assignment (org_id, exam_id, user_id, role)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (org_id, exam_id, user_id) DO UPDATE SET role = EXCLUDED.role`,
      [row.orgId, row.examId, row.userId, row.role],
    );
  });
}

export async function upsertEnrollmentToken(row: {
  id: string;
  enrollmentId: string;
  tokenHash: string;
  expiresAt: number;
  redeemed?: boolean;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO enrollment_token (id, enrollment_id, token_hash, expires_at, redeemed_at)
     VALUES ($1, $2, $3, to_timestamp($4 / 1000.0), $5)
     ON CONFLICT (id) DO UPDATE SET redeemed_at = EXCLUDED.redeemed_at`,
    [row.id, row.enrollmentId, row.tokenHash, row.expiresAt, row.redeemed ? new Date().toISOString() : null],
  );
}

export async function upsertDeviceTree(input: {
  device: { id: string; orgId: string; enrollmentId: string; kind: string; fingerprint?: string };
  familyId: string;
  familyRevoked?: boolean;
  refreshId?: string;
  refreshHash: string;
  refreshUsed?: boolean;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `INSERT INTO device (id, org_id, enrollment_id, kind, fingerprint)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (id) DO UPDATE SET fingerprint = EXCLUDED.fingerprint`,
      [input.device.id, input.device.orgId, input.device.enrollmentId, input.device.kind, input.device.fingerprint ?? null],
    );
    await client.query(
      `INSERT INTO device_credential_family (id, device_id, revoked_at)
       VALUES ($1, $2, $3)
       ON CONFLICT (id) DO UPDATE SET revoked_at = EXCLUDED.revoked_at`,
      [input.familyId, input.device.id, input.familyRevoked ? new Date().toISOString() : null],
    );
    await client.query(
      `INSERT INTO device_refresh_token (id, family_id, token_hash, used_at, expires_at)
       VALUES ($1, $2, $3, $4, now() + interval '30 days')
       ON CONFLICT (token_hash) DO UPDATE SET used_at = EXCLUDED.used_at`,
      [input.refreshId ?? `${input.familyId}:tok`, input.familyId, input.refreshHash, input.refreshUsed ? new Date().toISOString() : null],
    );
    await client.query("COMMIT");
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch {
      // already broken
    }
    throw err;
  } finally {
    client.release();
  }
}

export async function markRefreshUsed(tokenHash: string): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`UPDATE device_refresh_token SET used_at = now() WHERE token_hash = $1`, [tokenHash]);
}

export async function insertConsentRecord(row: { enrollmentId: string; body: unknown }): Promise<string> {
  const pool = getPool();
  if (!pool) return "";
  const res = await pool.query(
    `INSERT INTO consent_record (enrollment_id, body) VALUES ($1, $2::jsonb) RETURNING id`,
    [row.enrollmentId, JSON.stringify(row.body ?? {})],
  );
  return res.rows[0]?.id ?? "";
}

/* ---------------- sessions / events / commands ---------------- */

export async function insertSessionAttempt(row: {
  id: string;
  sessionId: string;
  enrollmentId: string;
  terminal: boolean;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO session_attempt (id, session_id, enrollment_id, terminal)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (id) DO UPDATE SET terminal = EXCLUDED.terminal, ended_at = CASE WHEN EXCLUDED.terminal THEN now() ELSE NULL END`,
    [row.id, row.sessionId, row.enrollmentId, row.terminal],
  );
}

export async function insertPrecheckResult(row: { sessionId: string; body: unknown }): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`INSERT INTO precheck_result (session_id, body) VALUES ($1, $2::jsonb)`, [
    row.sessionId,
    JSON.stringify(row.body ?? {}),
  ]);
}

export async function insertStatusTransition(row: {
  sessionId: string;
  fromState?: string;
  toState: string;
  desired: boolean;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO status_transition (session_id, from_state, to_state, desired) VALUES ($1, $2, $3, $4)`,
    [row.sessionId, row.fromState ?? null, row.toState, row.desired],
  );
}

export async function insertEventRejection(row: { sessionId: string; seq: number; code: string }): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`INSERT INTO event_rejection (session_id, seq_no, code) VALUES ($1, $2, $3)`, [
    row.sessionId,
    row.seq,
    row.code,
  ]);
}

export async function upsertIngestCursor(sessionId: string, ackedThrough: number): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO ingest_cursor (session_id, acked_through) VALUES ($1, $2)
     ON CONFLICT (session_id) DO UPDATE SET acked_through = GREATEST(ingest_cursor.acked_through, EXCLUDED.acked_through)`,
    [sessionId, ackedThrough],
  );
}

export async function insertCommandDelivery(row: { commandId: string; attempt: number }): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`INSERT INTO command_delivery (command_id, attempt) VALUES ($1, $2)`, [row.commandId, row.attempt]);
}

export async function insertOutbox(topic: string, payload: unknown): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`INSERT INTO outbox (topic, payload) VALUES ($1, $2::jsonb)`, [topic, JSON.stringify(payload ?? {})]);
}

export async function insertExamStream(examId: string, streamSeq: number, payload: unknown): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO exam_stream (exam_id, stream_seq, payload) VALUES ($1, $2, $3::jsonb) ON CONFLICT DO NOTHING`,
    [examId, streamSeq, JSON.stringify(payload ?? {})],
  );
}

/* ---------------- media / findings ---------------- */

export async function upsertMediaAsset(row: {
  id: string;
  orgId: string;
  sessionId: string;
  kind: string;
  objectKey: string;
  contentType: string;
  bytes: number;
  sha256: string;
  status: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO media_asset (id, org_id, session_id, kind, object_key, content_type, bytes, sha256, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status`,
      [row.id, row.orgId, row.sessionId, row.kind, row.objectKey, row.contentType, row.bytes, row.sha256, row.status],
    );
  });
}

export async function upsertMediaUpload(row: { id: string; assetId: string; expiresAt: number }): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO media_upload (id, asset_id, expires_at) VALUES ($1, $2, to_timestamp($3 / 1000.0))
     ON CONFLICT (id) DO NOTHING`,
    [row.id, row.assetId, row.expiresAt],
  );
}

export async function upsertEvidenceManifest(row: {
  id: string;
  sessionId: string;
  frozen: boolean;
  body: unknown;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO evidence_manifest (id, session_id, frozen, body) VALUES ($1, $2, $3, $4::jsonb)
     ON CONFLICT (id) DO UPDATE SET frozen = EXCLUDED.frozen, body = EXCLUDED.body`,
    [row.id, row.sessionId, row.frozen, JSON.stringify(row.body ?? {})],
  );
}

export async function insertDeadLetter(assetId: string, reason: string): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`INSERT INTO media_dead_letter (asset_id, reason) VALUES ($1, $2)`, [assetId, reason]);
}

export async function upsertFinding(row: {
  id: string;
  orgId: string;
  sessionId: string;
  eventSeq?: number;
  label: string;
  status: string;
  actorId?: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO finding (id, org_id, session_id, event_seq, label, status, actor_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label, status = EXCLUDED.status`,
      [row.id, row.orgId, row.sessionId, row.eventSeq ?? null, row.label, row.status, row.actorId ?? null],
    );
  });
}

export async function insertLabelRevision(row: { findingId: string; actorId: string; label: string }): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`INSERT INTO label_revision (finding_id, actor_id, label) VALUES ($1, $2, $3)`, [
    row.findingId,
    row.actorId,
    row.label,
  ]);
}

export async function insertReviewAssignment(findingId: string, reviewerId: string): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO review_assignment (id, finding_id, reviewer_id) VALUES (gen_random_uuid(), $1, $2)
     ON CONFLICT (finding_id, reviewer_id) DO NOTHING`,
    [findingId, reviewerId],
  );
}

export async function upsertReviewCase(row: {
  id: string;
  findingId: string;
  guidelineVersion: string;
  selectionProbability?: number;
  modalitiesViewed?: unknown;
  postIntervention: boolean;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO review_case (id, finding_id, guideline_version, selection_probability, modalities_viewed, post_intervention)
     VALUES ($1, $2, $3, $4, $5::jsonb, $6)
     ON CONFLICT (id) DO NOTHING`,
    [
      row.id,
      row.findingId,
      row.guidelineVersion,
      row.selectionProbability ?? null,
      row.modalitiesViewed === undefined ? null : JSON.stringify(row.modalitiesViewed),
      row.postIntervention,
    ],
  );
}

export async function upsertAppeal(row: {
  id: string;
  findingId: string;
  original?: string;
  appealReviewer?: string;
  outcome?: string;
  frozenManifestId?: string;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO appeal (id, finding_id, original_reviewer_id, appeal_reviewer_id, outcome, frozen_manifest_id)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (id) DO UPDATE SET outcome = EXCLUDED.outcome, appeal_reviewer_id = EXCLUDED.appeal_reviewer_id`,
    [row.id, row.findingId, row.original ?? null, row.appealReviewer ?? null, row.outcome ?? null, row.frozenManifestId ?? null],
  );
}

export async function freezeManifest(manifestId: string): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(`UPDATE evidence_manifest SET frozen = TRUE WHERE id = $1`, [manifestId]);
}

/* ---------------- exam content ---------------- */

export async function upsertBank(row: { id: string; orgId: string; name: string }): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO question_bank (id, org_id, name) VALUES ($1, $2, $3)
       ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name`,
      [row.id, row.orgId, row.name],
    );
  });
}

export async function upsertGroup(row: {
  id: string; orgId: string; bankId: string; position: number; title: string;
  marks: number; negativeMarks: number; rubric: string;
}): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO question_group (id, org_id, bank_id, position, title, marks, negative_marks, rubric)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, marks = EXCLUDED.marks,
         negative_marks = EXCLUDED.negative_marks, rubric = EXCLUDED.rubric`,
      [row.id, row.orgId, row.bankId, row.position, row.title, row.marks, row.negativeMarks, row.rubric],
    );
  });
}

export async function upsertContentVersion(row: { id: string; orgId: string; bankId: string; version: number }): Promise<void> {
  await withOrg(row.orgId, async (c) => {
    await c.query(
      `INSERT INTO content_version (id, org_id, bank_id, version) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING`,
      [row.id, row.orgId, row.bankId, row.version],
    );
  });
}

/** Atomic publish: version row + stamping draft variants in ONE transaction (no FK race). */
export async function publishContentVersion(
  ver: { id: string; orgId: string; bankId: string; version: number },
  variantIds: string[],
): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(`SELECT set_config('app.org_id', $1, true)`, [ver.orgId]);
    await client.query(
      `INSERT INTO content_version (id, org_id, bank_id, version) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING`,
      [ver.id, ver.orgId, ver.bankId, ver.version],
    );
    for (const vid of variantIds) {
      await client.query(`UPDATE question_variant SET content_version_id = $2 WHERE id = $1 AND content_version_id IS NULL`, [
        vid,
        ver.id,
      ]);
    }
    await client.query("COMMIT");
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch {
      // already broken
    }
    throw err;
  } finally {
    try {
      await client.query("RESET app.org_id");
    } catch {
      // connection may already be broken
    }
    client.release();
  }
}

export async function upsertVariantWithOptions(
  variant: {
    id: string; orgId: string; groupId: string; contentVersionId?: string;
    position: number; stem: string; qtype: string; perQuestionS?: number; deprecated?: boolean;
  },
  options: { id: string; orgId: string; variantId: string; position: number; label: string; correct: boolean }[],
): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `INSERT INTO question_variant (id, org_id, group_id, content_version_id, position, stem, qtype, per_question_s, deprecated)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       ON CONFLICT (id) DO UPDATE SET
         content_version_id = EXCLUDED.content_version_id,
         stem = EXCLUDED.stem, per_question_s = EXCLUDED.per_question_s, deprecated = EXCLUDED.deprecated`,
      [
        variant.id, variant.orgId, variant.groupId, variant.contentVersionId ?? null,
        variant.position, variant.stem, variant.qtype, variant.perQuestionS ?? null, !!variant.deprecated,
      ],
    );
    for (const o of options) {
      await client.query(
        `INSERT INTO question_option (id, org_id, variant_id, position, label, correct)
         VALUES ($1, $2, $3, $4, $5, $6)
         ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label, correct = EXCLUDED.correct`,
        [o.id, o.orgId, o.variantId, o.position, o.label, o.correct],
      );
    }
    await client.query("COMMIT");
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch {
      // already broken
    }
    throw err;
  } finally {
    client.release();
  }
}

export async function upsertExamContent(
  orgId: string,
  examId: string,
  input: { contentVersionId: string; allowBackNavigation?: boolean; durationS?: number },
): Promise<void> {
  await withOrg(orgId, async (c) => {
    await c.query(
      `UPDATE exam SET content_version_id = $2, allow_back_navigation = $3, duration_s = $4 WHERE id = $1`,
      [examId, input.contentVersionId, !!input.allowBackNavigation, input.durationS ?? null],
    );
  });
}

export async function upsertCandidateCode(row: {
  id: string; enrollmentId: string; codeHash: string; expiresAt: number;
  maxUses: number; uses?: number; redeemed?: boolean;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO candidate_login_code (id, enrollment_id, code_hash, expires_at, max_uses, uses, redeemed_at)
     VALUES ($1, $2, $3, to_timestamp($4 / 1000.0), $5, $6, $7)
     ON CONFLICT (id) DO UPDATE SET
       uses = EXCLUDED.uses, redeemed_at = EXCLUDED.redeemed_at, max_uses = EXCLUDED.max_uses`,
    [
      row.id, row.enrollmentId, row.codeHash, row.expiresAt, row.maxUses, row.uses ?? 0,
      row.redeemed ? new Date().toISOString() : null,
    ],
  );
}

export async function upsertCandidateSession(row: {
  id: string; sessionId: string; enrollmentId: string; tokenHash: string; expiresAt: number; revoked?: boolean; csrf?: string;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO candidate_session (id, session_id, enrollment_id, token_hash, csrf_secret, expires_at, revoked_at)
     VALUES ($1, $2, $3, $4, $5, to_timestamp($6 / 1000.0), $7)
     ON CONFLICT (id) DO UPDATE SET revoked_at = EXCLUDED.revoked_at`,
    [
      row.id, row.sessionId, row.enrollmentId, row.tokenHash, row.csrf ?? "",
      row.expiresAt, row.revoked ? new Date().toISOString() : null,
    ],
  );
}

export async function upsertAssignment(row: {
  sessionId: string; groupId: string; variantId: string; optionSeed: number; position: number;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO candidate_item_assignment (session_id, group_id, variant_id, option_seed, position)
     VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING`,
    [row.sessionId, row.groupId, row.variantId, row.optionSeed, row.position],
  );
}

export async function upsertAnswer(row: {
  id: string; sessionId: string; variantId: string; optionIds: string[];
  textAnswer: string; correct?: boolean; score?: number;
}): Promise<void> {
  const pool = getPool();
  if (!pool) return;
  await pool.query(
    `INSERT INTO candidate_answer (id, session_id, variant_id, option_ids, text_answer, correct, score)
     VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
     ON CONFLICT (session_id, variant_id) DO UPDATE SET
       option_ids = EXCLUDED.option_ids, text_answer = EXCLUDED.text_answer,
       correct = EXCLUDED.correct, score = EXCLUDED.score, submitted_at = now()`,
    [
      row.id, row.sessionId, row.variantId, JSON.stringify(row.optionIds),
      row.textAnswer, row.correct ?? null, row.score ?? null,
    ],
  );
}
