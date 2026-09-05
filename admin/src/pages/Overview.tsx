import React from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

interface Exam {
  id: string;
  code: string;
  title: string;
  status: string;
  version: number;
}

export function Overview() {
  const [view, setView] = React.useState<any>(null);
  const [exams, setExams] = React.useState<Exam[]>([]);
  const [banks, setBanks] = React.useState<any[]>([]);
  const [users, setUsers] = React.useState<any[]>([]);
  const [sessionsByExam, setSessionsByExam] = React.useState<Record<string, number>>({});
  const [err, setErr] = React.useState("");

  React.useEffect(() => {
    (async () => {
      try {
        const [v, e, b, u] = await Promise.all([
          api("/api/v1/platform/view"),
          api("/api/v1/exams"),
          api("/api/v1/banks"),
          api("/api/v1/admin/users"),
        ]);
        setView(v);
        setExams(e.items || []);
        setBanks(b.items || []);
        setUsers(u.items || []);
        const counts: Record<string, number> = {};
        await Promise.all(
          (e.items || []).map(async (exam: Exam) => {
            try {
              const s = await api(`/api/v1/console/snapshot?exam_id=${exam.id}`);
              counts[exam.id] = (s.sessions || []).length;
            } catch {
              counts[exam.id] = 0;
            }
          }),
        );
        setSessionsByExam(counts);
      } catch (e) {
        setErr(JSON.stringify(e));
      }
    })().catch(() => undefined);
  }, []);

  const checks = (view?.checks || {}) as Record<string, string>;
  const totalQuestions = banks.reduce(
    (n, b) => n + (b.groups || []).reduce((m: number, g: any) => m + (g.variants || []).length, 0),
    0,
  );
  const totalGroups = banks.reduce((n, b) => n + (b.groups || []).length, 0);
  const byStatus: Record<string, number> = {};
  for (const e of exams) byStatus[e.status] = (byStatus[e.status] || 0) + 1;
  const maxStatus = Math.max(1, ...Object.values(byStatus));

  return (
    <>
      <div className="pagehead">
        <h1>Overview</h1>
        <p className="muted">Live platform analytics — users, exams, content, sessions, dependencies.</p>
      </div>

      <div className="cards">
        <div className="card"><div className="muted">Staff users</div><div className="bignum">{users.length}</div></div>
        <div className="card"><div className="muted">Exams</div><div className="bignum">{exams.length}</div></div>
        <div className="card"><div className="muted">Live sessions</div><div className="bignum">{view?.sessions ?? "…"}</div></div>
        <div className="card"><div className="muted">Agents online</div><div className="bignum">{view?.agents_online ?? "…"}</div></div>
        <div className="card"><div className="muted">Question banks</div><div className="bignum">{banks.length}</div></div>
        <div className="card"><div className="muted">Groups / variants</div><div className="bignum">{totalGroups} / {totalQuestions}</div></div>
      </div>

      <div className="cards">
        <div className="card">
          <h3>Exams by status</h3>
          {Object.keys(byStatus).length === 0 && <p className="muted">No exams yet.</p>}
          {Object.entries(byStatus).map(([s, n]) => (
            <div key={s} style={{ display: "flex", alignItems: "center", gap: 8, margin: "6px 0" }}>
              <span style={{ width: 90 }}><span className={`badge b-${s.toLowerCase()}`}>{s}</span></span>
              <div style={{ flex: 1, height: 10, background: "#0b1322", borderRadius: 99 }}>
                <div style={{ width: `${(n / maxStatus) * 100}%`, height: "100%", borderRadius: 99, background: "#3b82f6" }} />
              </div>
              <b>{n}</b>
            </div>
          ))}
        </div>
        <div className="card">
          <h3>Dependencies</h3>
          {Object.keys(checks).length === 0 && <p className="muted">Loading…</p>}
          {Object.entries(checks).map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", margin: "6px 0" }}>
              <span className="muted">{k}</span>
              <span className={`badge b-${v === "ok" ? "ready" : v === "unconfigured" ? "warn" : "bad"}`}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Exams</h3>
        <table className="data">
          <thead><tr><th>Code</th><th>Title</th><th>Status</th><th>Sessions</th><th></th></tr></thead>
          <tbody>
            {exams.map((e) => (
              <tr key={e.id}>
                <td><b>{e.code}</b></td>
                <td>{e.title}</td>
                <td><span className={`badge b-${e.status.toLowerCase()}`}>{e.status}</span></td>
                <td>{sessionsByExam[e.id] ?? "…"}</td>
                <td><Link to={`/exams/${e.id}`}>Open →</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
        {exams.length === 0 && <p className="muted">No exams yet.</p>}
      </div>

      <div className="card">
        <h3>Staff users ({users.length})</h3>
        <table className="data">
          <thead><tr><th>Email</th><th>Name</th><th>Organization</th><th>Roles</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td className="muted">{u.name}</td>
                <td>{u.orgs.map((o: any) => o.org_name || o.org_id).join(", ")}</td>
                <td>{u.orgs.flatMap((o: any) => o.roles).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {err && <pre className="dump err">{err}</pre>}
    </>
  );
}
