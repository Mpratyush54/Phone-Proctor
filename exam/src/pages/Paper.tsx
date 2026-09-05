import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";

interface Item {
  done: boolean;
  position?: number;
  total?: number;
  answered?: number;
  variant_id?: string;
  group_title?: string;
  stem?: string;
  qtype?: string;
  per_question_s?: number | null;
  allow_back_navigation?: boolean;
  options?: { id: string; label: string }[];
}

export function Paper() {
  const nav = useNavigate();
  const exam = (useLocation().state as { exam?: { code: string; title: string } } | null)?.exam;
  const [item, setItem] = React.useState<Item | null>(null);
  const [picked, setPicked] = React.useState<string[]>([]);
  const [text, setText] = React.useState("");
  const [err, setErr] = React.useState("");
  const [left, setLeft] = React.useState<number | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  async function load() {
    setErr("");
    try {
      const next = await api("/api/v1/candidate/next-item");
      setItem(next);
      setPicked([]);
      setText("");
      setLeft(typeof next.per_question_s === "number" ? next.per_question_s : null);
    } catch (e) {
      setErr(JSON.stringify(e));
    }
  }

  React.useEffect(() => {
    load().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (left === null) return;
    if (left <= 0) {
      submit().catch(() => undefined);
      return;
    }
    const t = setTimeout(() => setLeft((v) => (v === null ? v : v - 1)), 1000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [left]);

  async function submit() {
    if (!item || item.done || submitting) return;
    setSubmitting(true);
    try {
      await api("/api/v1/candidate/answer", {
        method: "POST",
        body: JSON.stringify({ variant_id: item.variant_id, option_ids: picked, text_answer: text }),
      });
      setSubmitting(false);
      await load();
    } catch (e) {
      setSubmitting(false);
      setErr(JSON.stringify(e));
    }
  }

  async function logout() {
    await api("/api/v1/candidate/logout", { method: "POST", body: "{}" }).catch(() => undefined);
    nav("/");
  }

  if (!item) {
    return (
      <div className="wrap">
        <div className="card"><p className="muted">Loading…</p>{err && <pre className="err">{err}</pre>}</div>
      </div>
    );
  }
  if (item.done) {
    return (
      <div className="wrap">
        <div className="card">
          <h1>Submitted ✓</h1>
          <p className="muted">Answered {item.answered} of {item.total}. Your responses are recorded. You may now close this window.</p>
          <div className="toolbar"><button className="ghost" onClick={logout}>Log out</button></div>
        </div>
      </div>
    );
  }

  const multi = item.qtype === "mcq_multi";
  const pct = item.total ? Math.round(((item.answered || 0) / item.total) * 100) : 0;
  function toggle(id: string) {
    if (multi) setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
    else setPicked([id]);
  }

  return (
    <div className="wrap">
      <div className="topbar">
        <b>{exam ? `${exam.code} — ${exam.title}` : "Exam"}</b>
        <span className="muted">
          Q{item.position} of {item.total}
          {left !== null && <span className="timer"> · {left}s</span>}
        </span>
      </div>
      <div className="progress"><div style={{ width: `${pct}%` }} /></div>
      <div className="card">
        <p className="muted" style={{ marginTop: 0 }}>{item.group_title}</p>
        <h1 style={{ whiteSpace: "pre-wrap" }}>{item.stem}</h1>
        {item.qtype !== "short_text" && item.qtype !== "long_text" ? (
          <div style={{ marginTop: 12 }}>
            {item.options?.map((o) => (
              <label className="opt" key={o.id}>
                <input type={multi ? "checkbox" : "radio"} name="opt" checked={picked.includes(o.id)} onChange={() => toggle(o.id)} />
                <span>{o.label}</span>
              </label>
            ))}
          </div>
        ) : (
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={item.qtype === "long_text" ? 8 : 3} />
        )}
        <div className="toolbar">
          <button onClick={submit} disabled={submitting} style={{ flex: 1 }}>
            {submitting ? "Submitting…" : "Submit answer"}
          </button>
          <button className="ghost" onClick={logout}>Log out</button>
        </div>
        {err && <pre className="err">{err}</pre>}
      </div>
    </div>
  );
}
