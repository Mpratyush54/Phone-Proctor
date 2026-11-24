export type SessionSummary = Record<string, unknown> & { session_id: string };
export type Snapshot = {
  exam_id: string;
  stream_id?: string;
  stream_seq: number;
  readiness: string;
  sessions: SessionSummary[];
};
export type SnapshotPage = Snapshot & { next_cursor: number; total: number };
export type Delta = { exam_id: string; stream_seq: number; op: string; session_id?: string; patch?: Record<string, unknown>; payload?: unknown };
export type DeltaBatch = { items: Delta[]; stream_id?: string; stream_seq?: number; readiness?: string; resnapshot?: boolean };

export function applyDeltas(snapshot: Snapshot, batch: DeltaBatch): Snapshot | "resnapshot" {
  if (batch.resnapshot || batch.stream_id !== undefined && batch.stream_id !== snapshot.stream_id ||
      batch.stream_seq !== undefined && batch.stream_seq < snapshot.stream_seq) return "resnapshot";
  let streamSeq = snapshot.stream_seq;
  let updated: Map<string, SessionSummary> | undefined;
  for (const delta of batch.items) {
    if (delta.exam_id !== snapshot.exam_id) return "resnapshot";
    if (delta.stream_seq <= streamSeq) continue;
    if (delta.stream_seq !== streamSeq + 1) return "resnapshot";
    streamSeq = delta.stream_seq;
    const id = delta.session_id;
    if (!id || delta.op !== "remove" && !delta.patch) continue;
    updated ??= new Map(snapshot.sessions.map((session) => [session.session_id, session]));
    if (delta.op === "remove") {
      updated.delete(id);
      continue;
    }
    const existing = updated.get(id);
    if (!existing && (delta.op !== "upsert" || typeof delta.patch?.lifecycle !== "string" || typeof delta.patch.connectivity !== "string")) {
      return "resnapshot";
    }
    updated.set(id, { ...existing, ...delta.patch, session_id: id });
  }
  const readiness = batch.readiness ?? snapshot.readiness;
  if (streamSeq === snapshot.stream_seq && readiness === snapshot.readiness) return snapshot;
  return { ...snapshot, stream_seq: streamSeq, readiness, sessions: updated ? [...updated.values()] : snapshot.sessions };
}

export function applyDelta(snapshot: Snapshot, delta: Delta) {
  return applyDeltas(snapshot, { items: [delta] });
}
