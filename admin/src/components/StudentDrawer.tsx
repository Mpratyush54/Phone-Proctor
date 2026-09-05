import React from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

type Tab = "overview" | "commands" | "media" | "answers";

export function StudentDrawer() {
  const { id = "" } = useParams();
  const [tab, setTab] = React.useState<Tab>("overview");
  const [data, setData] = React.useState<any>(null);
  const [answers, setAnswers] = React.useState<any[]>([]);
  const [thumb, setThumb] = React.useState<{ available: boolean; url?: string } | null>(null);
  const [note, setNote] = React.useState("");
  const [live, setLive] = React.useState(false);

  async function refresh() {
    try {
      setData(await api(`/api/v1/sessions/${id}`));
    } catch {
      // ignore
    }
    try {
      setAnswers((await api(`/api/v1/sessions/${id}/answers`)).items);
    } catch {
      // answers endpoint may be unavailable
    }
  }

  React.useEffect(() => {
    refresh().catch(() => undefined);
    const t = setInterval(() => {
      if (live) refresh().catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [id, live]);

  async function send(type: string) {
    setNote("");
    try {
      const r = await api(`/api/v1/sessions/${id}/commands`, {
        method: "POST",
        body: JSON.stringify({ type, idempotency_key: crypto.randomUUID() }),
      });
      setNote(`${type}: ${JSON.stringify(r.status || r)}`);
      await refresh();
    } catch (e) {
      setNote(JSON.stringify(e));
    }
  }

  async function loadThumb() {
    setThumb(null);
    try {
      setThumb(await api(`/api/v1/sessions/${id}/thumbnail`));
    } catch (e) {
      setThumb({ available: false });
      setNote(JSON.stringify(e));
    }
  }

  const session = data?.session || {};
  const events = (data?.events || []) as { timestamp?: string; type?: string; data?: unknown }[];
  const commands = (data?.commands || []) as { id: string; type: string; status: string }[];

  return (
    <>
      <div className="pagehead">
        <h1>{String(data?.session?.displayName || session?.id || id)}</h1>
        {session.observed && <span className={`badge b-${String(session.observed).toLowerCase()}`}>{String(session.observed)}</span>}
        <label style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> live refresh
        </label>
      </div>
      <div className="tabs">
        {(["overview", "commands", "media", "answers"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="cards">
          <div className="card"><div className="muted">Lifecycle</div><div className="bignum" style={{ fontSize: 22 }}>{String(session.observed || "—")}</div></div>
          <div className="card"><div className="muted">Connectivity</div><div className="bignum" style={{ fontSize: 22 }}>{String(session.connectivity || "—")}</div></div>
          <div className="card"><div className="muted">Attention</div><div className="bignum" style={{ fontSize: 22 }}>{String(session.attention || "—")}</div></div>
          <div className="card">
            <div className="muted">Claim</div>
            <div style={{ marginTop: 8 }}>{String(session.claimOwner || "unclaimed")}</div>
            <div className="toolbar"><button className="small ghost" onClick={() => api(`/api/v1/sessions/${id}/claim`, { method: "POST", body: "{}" }).then(refresh)}>Claim</button></div>
          </div>
        </div>
      )}

      {tab === "overview" && (
        <>
          <h2>Recent events</h2>
          <div className="timeline">
            {events.slice().reverse().map((e, i) => (
              <div className="ev" key={i}>
                <time>{String(e.timestamp || "")}</time>
                <b>{String(e.type)}</b> <span className="muted">{JSON.stringify(e.data ?? e).slice(0, 160)}</span>
              </div>
            ))}
            {events.length === 0 && <p className="muted">No events yet.</p>}
          </div>
        </>
      )}

      {tab === "commands" && (
        <div className="card">
          <h3>Send command</h3>
          <div className="toolbar">
            {["WARN", "PAUSE", "RESUME", "EXAM_END"].map((t) => (
              <button key={t} className={t === "EXAM_END" ? "danger small" : "ghost small"} onClick={() => send(t)}>{t}</button>
            ))}
          </div>
          {note && <p className="muted">{note}</p>}
          <h3>History</h3>
          <table className="data">
            <thead><tr><th>Type</th><th>Status</th><th>ID</th></tr></thead>
            <tbody>
              {commands.map((c) => (
                <tr key={c.id}><td>{c.type}</td><td>{c.status}</td><td className="muted">{c.id.slice(0, 8)}</td></tr>
              ))}
            </tbody>
          </table>
          {commands.length === 0 && <p className="muted">No commands yet.</p>}
        </div>
      )}

      {tab === "media" && (
        <div className="card">
          <h3>Latest snapshot</h3>
          <div className="toolbar"><button className="ghost" onClick={loadThumb}>Load thumbnail</button></div>
          <div className="thumbbox">
            {thumb === null && "No thumbnail loaded."}
            {thumb !== null && !thumb.available && "No verified snapshots yet — or object storage is not configured."}
            {thumb?.available && thumb.url && <img src={thumb.url} alt="candidate snapshot" />}
          </div>
          <p className="muted">Opening media creates an audit record and uses a short-lived signed URL.</p>
        </div>
      )}

      {tab === "answers" && (
        <div className="card">
          <h3>Answers ({answers.length})</h3>
          <table className="data">
            <thead><tr><th>Question</th><th>Picked</th><th>Correct</th><th>Score</th></tr></thead>
            <tbody>
              {answers.map((a: any) => (
                <tr key={a.id}>
                  <td style={{ maxWidth: 320 }}>{String(a.stem || a.variant_id).slice(0, 80)}</td>
                  <td className="muted">{(a.option_ids || []).length} option(s)</td>
                  <td>{a.correct === true ? "✓" : a.correct === false ? "✗" : "manual"}</td>
                  <td>{a.score ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {answers.length === 0 && <p className="muted">No answers submitted yet.</p>}
        </div>
      )}
    </>
  );
}
