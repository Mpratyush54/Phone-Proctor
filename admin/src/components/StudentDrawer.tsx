import React from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export function StudentDrawer() {
  const { id = "" } = useParams();
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
