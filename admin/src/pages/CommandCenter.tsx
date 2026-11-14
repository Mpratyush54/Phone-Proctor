import React from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { LiveGrid } from "../components/LiveGrid";
import { ExamSetup } from "./ExamSetup";
import { applyDelta, type Snapshot } from "../stream";

export function CommandCenter() {
  const { id = "" } = useParams();
  const [snap, setSnap] = React.useState<Snapshot | null>(null);
  const [ready, setReady] = React.useState("");
  async function loadSnapshot() {
    const s = (await api(`/api/v1/console/snapshot?exam_id=${id}`)) as Snapshot;
    setSnap(s);
    setReady((await api(`/api/v1/exams/${id}/readiness`)).readiness);
    return s;
  }
  React.useEffect(() => {
    let stop = false;
    let current: Snapshot | null = null;
    (async () => {
      try {
        current = await loadSnapshot();
      } catch {
        return;
      }
      while (!stop && current) {
        await new Promise((r) => setTimeout(r, 1000));
        if (stop || !current) break;
        try {
          const d = await api(`/api/v1/console/deltas?exam_id=${id}&after_seq=${current.stream_seq}`);
          for (const item of d.items || []) {
            const applied = applyDelta(current, item);
            if (applied === "resnapshot") {
              current = await loadSnapshot();
              break;
            }
            current = applied;
          }
          if (!stop && current) setSnap(current);
        } catch {
          current = await loadSnapshot();
        }
      }
    })();
    return () => {
      stop = true;
    };
  }, [id]);
  return (
    <main>
      <h1>Command center</h1>
      <p>Readiness (server-derived): <b>{ready || snap?.readiness}</b></p>
      <ExamSetup embedded onChanged={loadSnapshot} />
      <button
        onClick={async () => {
          const ids = (snap?.sessions || []).map((s) => s.session_id);
          const r = await api(`/api/v1/exams/${id}/commands/bulk`, {
            method: "POST",
            body: JSON.stringify({ session_ids: ids, type: "WARN", idempotency_key: crypto.randomUUID() }),
          });
          alert(JSON.stringify(r));
        }}
      >
        Bulk warn (server receipts)
      </button>
      <p>Grid uses snapshot then `/api/v1/console/deltas` with `stream_seq`. A gap forces resnapshot.</p>
      <LiveGrid sessions={snap?.sessions || []} />
    </main>
  );
}
