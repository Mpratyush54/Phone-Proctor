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

  if (!item) return <main style={{ padding: 24 }}>Loading…{err && <pre>{err}</pre>}</main>;
  if (item.done) {
    return (
      <main style={{ maxWidth: 560, margin: "4rem auto", fontFamily: "system-ui" }}>
        <h1>Submitted</h1>
        <p>
          Answered {item.answered} of {item.total}. Your responses are recorded. You may now close this window.
        </p>
        <button onClick={logout}>Log out</button>
      </main>
    );
  }

  const multi = item.qtype === "mcq_multi";
  function toggle(id: string) {
    if (multi) setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
    else setPicked([id]);
  }

  return (
    <main style={{ maxWidth: 640, margin: "2rem auto", fontFamily: "system-ui" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <b>{exam ? `${exam.code} — ${exam.title}` : "Exam"}</b>
        <span>
          Q{item.position} of {item.total} · answered {item.answered}
          {left !== null && <span> · {left}s left</span>}
        </span>
      </header>
      <p style={{ color: "#555" }}>{item.group_title}</p>
      <h2 style={{ whiteSpace: "pre-wrap" }}>{item.stem}</h2>
      {item.qtype !== "short_text" && item.qtype !== "long_text" ? (
        <div>
          {item.options?.map((o) => (
            <label key={o.id} style={{ display: "block", padding: "8px 0" }}>
              <input type={multi ? "checkbox" : "radio"} name="opt" checked={picked.includes(o.id)} onChange={() => toggle(o.id)} />{" "}
              {o.label}
            </label>
          ))}
        </div>
      ) : (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={item.qtype === "long_text" ? 8 : 3}
          style={{ width: "100%" }}
        />
      )}
      <div style={{ marginTop: 16 }}>
        <button onClick={submit} disabled={submitting}>
          {submitting ? "Submitting…" : "Submit answer"}
        </button>{" "}
        <button onClick={logout}>Log out</button>
      </div>
      {err && <pre style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{err}</pre>}
    </main>
  );
}
