import React from "react";
import { api } from "../api/client";

export function PlatformHealth() {
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
