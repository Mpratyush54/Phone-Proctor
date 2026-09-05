import React from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { LiveGrid } from "../components/LiveGrid";
import { ExamSetup } from "./ExamSetup";
import { applyDelta, type Snapshot } from "../stream";

const LIFECYCLE = ["EXAM_START", "PAUSE", "RESUME", "EXAM_END"] as const;

export function CommandCenter() {
  const { id = "" } = useParams();
  const [snap, setSnap] = React.useState<Snapshot | null>(null);
  const [ready, setReady] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [note, setNote] = React.useState("");
  async function loadSnapshot() {
    const s = (await api(`/api/v1/console/snapshot?exam_id=${id}`)) as Snapshot;
    setSnap(s);
    try {
      setReady((await api(`/api/v1/exams/${id}/readiness`)).readiness);
    } catch {
      // readiness endpoint optional
    }
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

  async function lifecycle(type: (typeof LIFECYCLE)[number]) {
    if (type === "EXAM_END" && !window.confirm("End the exam for ALL sessions? This needs no undo.")) return;
    setBusy(type);
    setNote("");
    try {
      const ids = (snap?.sessions || []).map((s) => s.session_id);
      const r = await api(`/api/v1/exams/${id}/commands/bulk`, {
        method: "POST",
        body: JSON.stringify({ session_ids: ids, type, idempotency_key: crypto.randomUUID() }),
      });
      const failed = (r.results || []).filter((x: { ok: boolean }) => !x.ok).length;
      setNote(`${type}: ${ids.length - failed}/${ids.length} accepted${failed ? `, ${failed} failed` : ""}`);
      await loadSnapshot();
    } catch (e) {
      setNote(JSON.stringify(e));
    }
    setBusy("");
  }

  const sessions = snap?.sessions || [];
  const online = sessions.filter((s) => String(s.connectivity) === "online").length;
  const flagged = sessions.filter((s) => String(s.attention) === "flagged").length;

  return (
    <>
      <div className="pagehead">
        <h1>Command center</h1>
        <span className={`badge b-${String(ready || snap?.readiness || "unknown").toLowerCase()}`}>
          {ready || snap?.readiness || "…"}
        </span>
      </div>
      <div className="cards">
        <div className="card"><div className="muted">Sessions</div><div className="bignum">{sessions.length}</div></div>
        <div className="card"><div className="muted">Online</div><div className="bignum">{online}</div></div>
        <div className="card"><div className="muted">Flagged</div><div className="bignum">{flagged}</div></div>
        <div className="card"><div className="muted">Stream seq</div><div className="bignum">{snap?.stream_seq ?? "…"}</div></div>
      </div>
      <div className="card">
        <h3>Lifecycle</h3>
        <div className="toolbar">
          {LIFECYCLE.map((t) => (
            <button key={t} className={t === "EXAM_END" ? "danger" : t === "EXAM_START" ? "" : "ghost"} disabled={!!busy} onClick={() => lifecycle(t)}>
              {busy === t ? "Sending…" : t.replace("EXAM_", "")}
            </button>
          ))}
          <button
            className="ghost"
            disabled={!!busy}
            onClick={async () => {
              const ids = sessions.map((s) => s.session_id);
              const r = await api(`/api/v1/exams/${id}/commands/bulk`, {
                method: "POST",
                body: JSON.stringify({ session_ids: ids, type: "WARN", idempotency_key: crypto.randomUUID() }),
              });
              setNote(`WARN: ${JSON.stringify(r.results?.length ?? 0)} receipts`);
            }}
          >
            Warn all
          </button>
        </div>
        {note && <p className="muted">{note}</p>}
      </div>
      <div className="card">
        <h3>Setup & roster</h3>
        <ExamSetup embedded onChanged={loadSnapshot} />
      </div>
      <LiveGrid sessions={sessions} />
    </>
  );
}
