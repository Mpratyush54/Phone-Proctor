import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { applyDelta, type Snapshot } from "./stream";

const qc = new QueryClient();
let csrf = "";

async function api(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") headers.set("x-csrf-token", csrf);
  headers.set("content-type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  const data = await res.json();
  if (!res.ok) throw data;
  return data;
}

function Login() {
  const [err, setErr] = React.useState("");
  return (
    <main>
      <h1>Staff login</h1>
      <p>Same-origin OIDC session. Access tokens are never stored in localStorage.</p>
      <button
        onClick={async () => {
          try {
            const cb = await api("/api/v1/auth/dev-login", { method: "POST", body: "{}" });
            csrf = cb.csrf;
            window.location.href = "/exams";
          } catch (e) {
            setErr(JSON.stringify(e));
          }
        }}
      >
        Continue with OIDC
      </button>
      <pre>{err}</pre>
    </main>
  );
}

function useMe() {
  const [me, setMe] = React.useState<Record<string, unknown> | null>(null);
  React.useEffect(() => {
    api("/api/v1/me")
      .then((m) => {
        csrf = m.csrf;
        setMe(m);
      })
      .catch(() => setMe(null));
  }, []);
  return me;
}

function Guard({ children, perm }: { children: React.ReactNode; perm?: string }) {
  const me = useMe();
  if (me === null) return <Navigate to="/login" replace />;
  if (perm && Array.isArray(me.permissions) && !me.permissions.includes(perm) && !me.permissions.includes("platform.ops")) {
    return <main>Missing permission {perm}</main>;
  }
  return <>{children}</>;
}

function Exams() {
  const [code, setCode] = React.useState("CS101");
  const [items, setItems] = React.useState<Array<{ id: string; code: string; title: string }>>([]);
  async function refresh() {
    const data = await api("/api/v1/exams");
    setItems(data.items);
  }
  React.useEffect(() => {
    refresh().catch(() => undefined);
  }, []);
  return (
    <main>
      <h1>Exam setup</h1>
      <input value={code} onChange={(e) => setCode(e.target.value)} />
      <button
        onClick={async () => {
          await api("/api/v1/exams", { method: "POST", body: JSON.stringify({ code, title: code, policy: { camera: true, microphone: true } }) });
          await refresh();
        }}
      >
        Create
      </button>
      <ul>
        {items.map((e) => (
          <li key={e.id}>
            <Link to={`/exams/${e.id}`}>{e.code}</Link> {e.title}
          </li>
        ))}
      </ul>
    </main>
  );
}

function Exam({ id }: { id: string }) {
  const [csv, setCsv] = React.useState("student_external_id,display_name\ns1,Ada");
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
      <button onClick={() => api(`/api/v1/exams/${id}/open`, { method: "POST", body: "{}" }).then(loadSnapshot)}>Open exam</button>
      <h2>Roster CSV</h2>
      <textarea rows={4} cols={60} value={csv} onChange={(e) => setCsv(e.target.value)} />
      <button
        onClick={async () => {
          const rows = csv
            .trim()
            .split("\n")
            .slice(1)
            .map((line) => {
              const [student_external_id, display_name] = line.split(",");
              return { student_external_id, display_name };
            });
          await api(`/api/v1/exams/${id}/roster`, { method: "POST", body: JSON.stringify({ rows }) });
          await loadSnapshot();
        }}
      >
        Import
      </button>
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
      <h2>Live grid</h2>
      <div className="grid">
        {(snap?.sessions || []).map((s) => (
          <Link className="cell" key={s.session_id} to={`/sessions/${s.session_id}`}>
            <div>{String(s.display_name || s.session_id)}</div>
            <div>{String(s.lifecycle)} / {String(s.connectivity)}</div>
            <div>thumb: {String(s.thumbnail_available)}</div>
          </Link>
        ))}
      </div>
    </main>
  );
}

function Drawer({ id }: { id: string }) {
  const [data, setData] = React.useState<Record<string, unknown> | null>(null);
  React.useEffect(() => {
    api(`/api/v1/sessions/${id}`).then(setData).catch(() => undefined);
  }, [id]);
  const session = (data?.session || {}) as { id?: string };
  return (
    <main>
      <h1>Student drawer</h1>
      <p>Overview / timeline / media / health / commands. Media opens are audited.</p>
      <pre>{JSON.stringify(data, null, 2)}</pre>
      <button onClick={() => api(`/api/v1/sessions/${id}/commands`, { method: "POST", body: JSON.stringify({ type: "WARN", idempotency_key: crypto.randomUUID() }) })}>
        Warn
      </button>
      <button onClick={() => api(`/api/v1/sessions/${id}/claim`, { method: "POST", body: "{}" })}>Claim</button>
    </main>
  );
}

function Shell() {
  return (
    <>
      <header>
        <b>Phone-Proctor</b>
        <Link to="/exams">Exams</Link>
        <Link to="/review">Review</Link>
        <Link to="/platform">Platform</Link>
        <Link to="/login">Login</Link>
      </header>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/exams" element={<Guard perm="exam.read"><Exams /></Guard>} />
        <Route path="/exams/:id" element={<Guard perm="exam.read"><ExamGate /></Guard>} />
        <Route path="/sessions/:id" element={<Guard perm="session.read"><SessionGate /></Guard>} />
        <Route path="/review" element={<Guard perm="review.annotate"><main><h1>Event-first review</h1><p>Blind annotation: identity and scores hidden until submit.</p></main></Guard>} />
        <Route path="/platform" element={<Guard perm="platform.ops"><Platform /></Guard>} />
        <Route path="/" element={<Navigate to="/exams" replace />} />
      </Routes>
    </>
  );
}

function ExamGate() {
  const id = window.location.pathname.split("/")[2];
  return <Exam id={id} />;
}
function SessionGate() {
  const id = window.location.pathname.split("/")[2];
  return <Drawer id={id} />;
}

function Platform() {
  const [view, setView] = React.useState<Record<string, unknown> | null>(null);
  React.useEffect(() => {
    api("/api/v1/platform/view").then(setView).catch(() => setView({ error: "unavailable" }));
  }, []);
  return (
    <main>
      <h1>Platform view</h1>
      <p>Tenant-blind. Redis failure is still visible on `/api/v1/health/aggregate`.</p>
      <pre>{JSON.stringify(view, null, 2)}</pre>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={qc}>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </QueryClientProvider>,
);
