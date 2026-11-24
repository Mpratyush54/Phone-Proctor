import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { Badge, Failure, PageHeading, State } from "../components/ui";

function label(key: string) {
  return key.replaceAll("_", " ").replace(/([a-z])([A-Z])/g, "$1 $2");
}

export function PlatformHealth() {
  const health = useQuery({
    queryKey: ["platform"],
    queryFn: async ({ signal }) => {
      const [checks, platform] = await Promise.all([
        api<Record<string, unknown>>("/api/v1/health/aggregate", { signal }),
        api<Record<string, unknown>>("/api/v1/platform/view", { signal }),
      ]);
      return { checks, platform };
    },
    refetchInterval: 10_000,
  });
  return <main>
    <PageHeading title="Platform health" description="Service checks and platform counters from the control plane."
      actions={<button disabled={health.isFetching} onClick={() => void health.refetch()}><RefreshCw size={16} /> Refresh</button>} />
    {health.isPending ? <State kind="loading" title="Loading service checks" /> : !health.data ? <Failure error={health.error} retry={() => void health.refetch()} /> : <>
      {health.isError && <div className="notice" role="alert">Updates interrupted. Showing the last successful health report.</div>}
      <section className="panel padded"><h2>Service checks</h2><dl className="metric-grid">
        {Object.entries(health.data.checks).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === "string" ? <Badge value={value} /> : <Output value={value} />}</dd></div>)}
      </dl></section>
      <section className="panel padded"><h2>Platform counters</h2><dl className="metric-grid">
        {Object.entries(health.data.platform).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd><Output value={value} /></dd></div>)}
      </dl></section>
    </>}
  </main>;
}

function Output({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <>Unknown</>;
  if (typeof value === "boolean") return <>{value ? "Enabled" : "Disabled"}</>;
  if (typeof value === "object") return <code>{JSON.stringify(value)}</code>;
  return <>{String(value)}</>;
}
