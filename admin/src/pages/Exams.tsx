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

export function Exams() {
  const [code, setCode] = React.useState("CS101");
  const [items, setItems] = React.useState<Exam[]>([]);
  const [err, setErr] = React.useState("");
  async function refresh() {
    try {
      const data = await api("/api/v1/exams");
      setItems(data.items);
    } catch (e) {
      setErr(JSON.stringify(e));
    }
  }
  React.useEffect(() => {
    refresh().catch(() => undefined);
  }, []);
  return (
    <>
      <div className="pagehead">
        <h1>Exams</h1>
        <p className="muted">{items.length} exam(s)</p>
      </div>
      <div className="card">
        <h3>Create exam</h3>
        <div className="toolbar">
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Exam code" />
          <button
            onClick={async () => {
              await api("/api/v1/exams", { method: "POST", body: JSON.stringify({ code, title: code, policy: { camera: true, microphone: true } }) });
              await refresh();
            }}
          >
            Create
          </button>
        </div>
      </div>
      <div className="cards">
        {items.map((e) => (
          <Link key={e.id} to={`/exams/${e.id}`} style={{ textDecoration: "none", color: "inherit" }}>
            <div className="card">
              <h3>{e.code}</h3>
              <div className="muted">{e.title}</div>
              <div style={{ marginTop: 8 }}>
                <span className={`badge b-${e.status.toLowerCase()}`}>{e.status}</span>{" "}
                <span className="muted">v{e.version}</span>
              </div>
            </div>
          </Link>
        ))}
      </div>
      {items.length === 0 && <p className="muted">No exams yet — create one above, then open it from its command center.</p>}
      {err && <pre className="dump err">{err}</pre>}
    </>
  );
}
