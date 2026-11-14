import React from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

export function Exams() {
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
