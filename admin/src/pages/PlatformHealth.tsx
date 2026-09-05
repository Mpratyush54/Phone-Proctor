import React from "react";
import { api } from "../api/client";

export function PlatformHealth() {
  const [view, setView] = React.useState<Record<string, unknown> | null>(null);
  const [agg, setAgg] = React.useState<Record<string, unknown> | null>(null);
  React.useEffect(() => {
    api("/api/v1/platform/view").then(setView).catch(() => setView({ error: "unavailable" }));
    api("/api/v1/health/aggregate").then(setAgg).catch(() => setAgg({ error: "unavailable" }));
  }, []);
  const checks = (agg?.checks || (view as any)?.checks || {}) as Record<string, string>;
  return (
    <>
      <div className="pagehead">
        <h1>Platform health</h1>
        <p className="muted">Tenant-blind. Dependency state stays visible through outages.</p>
      </div>
      <div className="cards">
        {Object.entries(checks).map(([k, v]) => (
          <div className="card" key={k}>
            <div className="muted">{k}</div>
            <div style={{ marginTop: 6 }}><span className={`badge b-${v === "ok" ? "ready" : v === "unconfigured" ? "warn" : "bad"}`}>{v}</span></div>
          </div>
        ))}
        {Object.keys(checks).length === 0 && <p className="muted">Loading…</p>}
      </div>
      <div className="card">
        <h3>Raw view</h3>
        <pre className="dump">{JSON.stringify({ view, agg }, null, 2)}</pre>
      </div>
    </>
  );
}
