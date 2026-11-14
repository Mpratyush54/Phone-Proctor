export type Snapshot = {
  exam_id: string;
  stream_seq: number;
  readiness: string;
  sessions: Array<Record<string, unknown> & { session_id: string }>;
};

export type Delta = { exam_id: string; stream_seq: number; op: string; session_id?: string; patch?: Record<string, unknown>; payload?: unknown };

export function applyDelta(snap: Snapshot, delta: Delta): Snapshot | "resnapshot" {
  if (delta.stream_seq <= snap.stream_seq) return snap; // duplicate ignored
  if (delta.stream_seq !== snap.stream_seq + 1) return "resnapshot";
  const sessions = snap.sessions.map((s) => ({ ...s }));
  if (delta.op === "remove" && delta.session_id) {
    return { ...snap, stream_seq: delta.stream_seq, sessions: sessions.filter((s) => s.session_id !== delta.session_id) };
  }
  if (delta.session_id && delta.patch) {
    const idx = sessions.findIndex((s) => s.session_id === delta.session_id);
    if (idx >= 0) sessions[idx] = { ...sessions[idx], ...delta.patch };
  }
  return { ...snap, stream_seq: delta.stream_seq, sessions };
}
