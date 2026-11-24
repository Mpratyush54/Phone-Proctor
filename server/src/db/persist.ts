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

/** Serialize related writes and let callers await their own result when needed. */
export function enqueuePersist<T>(work: () => Promise<T>): Promise<T | undefined> {
  if (!getPool()) return Promise.resolve(undefined);
  const result = persistChain.then(work);
  persistChain = result.then(
    () => undefined,
    (err: unknown) => {
      log.warn({ err }, "postgres persist failed");
    },
  );
  return result;
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
         control_generation, connection_generation, connectivity, attention
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
       ON CONFLICT (id) DO UPDATE SET
         desired_lifecycle_state = EXCLUDED.desired_lifecycle_state,
         observed_lifecycle_state = EXCLUDED.observed_lifecycle_state,
         control_generation = EXCLUDED.control_generation,
         connection_generation = EXCLUDED.connection_generation,
         connectivity = EXCLUDED.connectivity,
         attention = EXCLUDED.attention`,
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
}): Promise<number | undefined> {
  return withOrg(row.orgId, async (c) => {
    const insert = await c.query(
      `INSERT INTO event (org_id, session_id, seq_no, batch_id, payload_hash, payload)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)
       ON CONFLICT (session_id, seq_no) DO NOTHING`,
      [row.orgId, row.sessionId, row.seq, row.batchId, row.hash, JSON.stringify(row.payload ?? {})],
    );
    if (!insert.rowCount) {
      const existing = await c.query<{ payload_hash: string }>(
        "SELECT payload_hash FROM event WHERE session_id = $1 AND seq_no = $2",
        [row.sessionId, row.seq],
      );
      if (existing.rows[0]?.payload_hash !== row.hash) {
        throw Object.assign(new Error("same seq different hash"), { code: "HASH_MISMATCH" });
      }
    } else {
      await c.query(
        "INSERT INTO outbox (topic, payload) VALUES ('event.ingested', $1::jsonb)",
        [JSON.stringify({ session_id: row.sessionId, seq: row.seq })],
      );
    }
    await c.query("INSERT INTO ingest_cursor (session_id) VALUES ($1) ON CONFLICT DO NOTHING", [row.sessionId]);
    const cursor = await c.query<{ acked_through: string }>(
      "SELECT acked_through FROM ingest_cursor WHERE session_id = $1 FOR UPDATE",
      [row.sessionId],
    );
    const acked = Number(cursor.rows[0].acked_through);
    if (row.seq !== acked + 1) return acked;
    const next = await c.query<{ acked: string }>(
      `WITH pending AS (
         SELECT seq_no, row_number() OVER (ORDER BY seq_no) AS seq_rank
         FROM event WHERE session_id = $1 AND seq_no > $2::bigint
       )
       SELECT COALESCE(MIN($2::bigint + seq_rank - 1) FILTER (WHERE seq_no <> $2::bigint + seq_rank), MAX(seq_no), $2::bigint) AS acked
       FROM pending`,
      [row.sessionId, acked],
    );
    const through = Number(next.rows[0].acked);
    await c.query("UPDATE ingest_cursor SET acked_through = $2 WHERE session_id = $1", [row.sessionId, through]);
    return through;
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
