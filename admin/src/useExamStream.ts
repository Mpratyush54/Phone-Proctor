import { useEffect, useState } from "react";
import { api, ApiError, describeError } from "./api/client";
import { applyDeltas, type DeltaBatch, type Snapshot, type SnapshotPage } from "./stream";

type Feed =
  | { phase: "loading"; snapshot: null }
  | { phase: "live" | "syncing"; snapshot: Snapshot }
  | { phase: "stale"; snapshot: Snapshot; error: string }
  | { phase: "error"; snapshot: null; error: string };

async function loadSnapshot(id: string, signal: AbortSignal): Promise<Snapshot> {
  const first = await api<SnapshotPage>(`/api/v1/console/snapshot?exam_id=${id}&limit=500`, { signal });
  const sessions = new Map(first.sessions.map((session) => [session.session_id, session]));
  let cursor = first.next_cursor;
  const total = first.total;
  while (cursor < total) {
    const page = await api<SnapshotPage>(`/api/v1/console/snapshot?exam_id=${id}&limit=500&cursor=${cursor}`, { signal });
    if (page.exam_id !== first.exam_id || page.stream_id !== first.stream_id || page.next_cursor <= cursor) {
      throw new Error("The monitoring feed changed while loading. Reconnecting.");
    }
    for (const session of page.sessions) sessions.set(session.session_id, session);
    cursor = page.next_cursor;
  }
  return { exam_id: first.exam_id, stream_id: first.stream_id, stream_seq: first.stream_seq, readiness: first.readiness, sessions: [...sessions.values()] };
}

export function useExamStream(id: string, enabled: boolean) {
  const [feed, setFeed] = useState<Feed>({ phase: "loading", snapshot: null });
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const { signal } = controller;
    let timer: ReturnType<typeof setTimeout>;
    let current: Snapshot | null = null;
    let needsSnapshot = true;
    let consecutiveFailures = 0;

    async function poll() {
      try {
        const deadline = AbortSignal.any([signal, AbortSignal.timeout(12_000)]);
        if (needsSnapshot || !current) {
          current = await loadSnapshot(id, deadline);
          needsSnapshot = false;
        }
        const params = new URLSearchParams({ exam_id: id, after_seq: String(current.stream_seq) });
        if (current.stream_id) params.set("stream_id", current.stream_id);
        const batch = await api<DeltaBatch>(`/api/v1/console/deltas?${params}`, { signal: deadline });
        if (signal.aborted) return;
        const next = applyDeltas(current, batch);
        if (next === "resnapshot") {
          needsSnapshot = true;
          setFeed({ phase: "syncing", snapshot: current });
          timer = setTimeout(poll, 250);
          return;
        }
        const catchingUp = (batch.stream_seq ?? next.stream_seq) > next.stream_seq;
        if (catchingUp && next.stream_seq === current.stream_seq) throw new Error("The monitoring feed stopped advancing.");
        current = next;
        consecutiveFailures = 0;
        const phase = catchingUp ? "syncing" : "live";
        setFeed((previous) => previous.phase === phase && previous.snapshot === next ? previous : { phase, snapshot: next });
        timer = setTimeout(poll, catchingUp ? 0 : 1_000);
      } catch (error) {
        if (signal.aborted) return;
        const message = describeError(error);
        setFeed(current ? { phase: "stale", snapshot: current, error: message } : { phase: "error", snapshot: null, error: message });
        if (error instanceof ApiError && [401, 403, 404].includes(error.status)) return;
        consecutiveFailures += 1;
        timer = setTimeout(poll, Math.min(10_000, 1_000 * 2 ** consecutiveFailures));
      }
    }

    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, enabled, generation]);

  return { feed, retry: () => setGeneration((value) => value + 1) };
}
