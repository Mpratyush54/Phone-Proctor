import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Activity, ArrowLeft, Radio, Settings2, TriangleAlert, Users } from "lucide-react";
import { api } from "../api/client";
import { usePermissions } from "../auth";
import { LiveGrid } from "../components/LiveGrid";
import { Badge, Failure, Feedback, PageHeading, State } from "../components/ui";
import { useExamStream } from "../useExamStream";
import type { Exam } from "./Exams";

type Receipt = { session_id: string; ok: boolean; status?: string; error?: string };

export function CommandCenter() {
  const { id = "" } = useParams();
  return <Monitoring key={id} id={id} />;
}

function Monitoring({ id }: { id: string }) {
  const allowed = usePermissions();
  const [selected, setSelected] = React.useState(new Set<string>());
  const [confirm, setConfirm] = React.useState(false);
  const exam = useQuery({ queryKey: ["exam", id], queryFn: ({ signal }) => api<Exam>(`/api/v1/exams/${id}`, { signal }) });
  const { feed, retry } = useExamStream(id, exam.isSuccess);
  const snapshot = feed.snapshot;
  const activeSelection = snapshot?.sessions.filter((session) => session.connectivity === "online" && session.lifecycle !== "ENDED" && selected.has(session.session_id)).map((session) => session.session_id) ?? [];
  const warn = useMutation({
    mutationFn: (ids: string[]) => api<{ results: Receipt[] }>(`/api/v1/exams/${id}/commands/bulk`, {
      method: "POST", body: JSON.stringify({ session_ids: ids, type: "WARN", idempotency_key: crypto.randomUUID() }),
    }),
    onSuccess: (data) => {
      const accepted = new Set(data.results.filter((receipt) => receipt.ok).map((receipt) => receipt.session_id));
      setSelected((previous) => new Set([...previous].filter((sessionId) => !accepted.has(sessionId))));
    },
  });
  function toggle(sessionId: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(sessionId)) next.delete(sessionId);
      else next.add(sessionId);
      return next;
    });
  }
  const online = snapshot?.sessions.filter((session) => session.connectivity === "online").length;
  const rejected = warn.data?.results.filter((receipt) => !receipt.ok) ?? [];
  if (exam.isPending) return <main><State kind="loading" title="Loading exam" /></main>;
  if (exam.isError) return <main><Failure title="Could not open the exam" error={exam.error} retry={() => void exam.refetch()} /></main>;
  return <main>
    <Link className="back-link" to="/monitor"><ArrowLeft size={16} /> Monitoring</Link>
    <PageHeading title={exam.data.title} description={`${exam.data.code} · Live monitoring`}
      actions={<Link className="button" to={`/exams/${id}/setup`}><Settings2 size={17} /> Exam setup</Link>} />
    <div className="overview-stats monitoring-stats">
      <div className="stat"><span className="feature-icon"><Users size={19} /></span><span>Candidate sessions<strong>{snapshot?.sessions.length ?? "—"}</strong></span></div>
      <div className="stat"><span className="feature-icon mint"><Activity size={19} /></span><span>Online<strong>{online ?? "—"}</strong></span></div>
      <div className="stat"><span className="feature-icon gold"><Radio size={19} /></span><span>Exam readiness<strong className="stat-status">{snapshot?.sessions.length ? <Badge value={snapshot.readiness} /> : <span>Awaiting sessions</span>}</strong></span></div>
    </div>
    <section className="panel">
      <div className="panel-heading"><div><h2>Candidate sessions</h2><p>Select a candidate to inspect their latest activity.</p></div>
        <span className={`live-indicator ${feed.phase === "live" ? "is-live" : ""}`} role="status"><i />{{ loading: "Connecting", live: "Live updates", syncing: "Synchronizing", stale: "Updates interrupted", error: "Unavailable" }[feed.phase]}</span>
      </div>
      {feed.phase === "loading" && <State title="Connecting to monitoring" kind="loading" />}
      {feed.phase === "error" && <Failure title="Could not load the monitoring feed" error={new Error(feed.error)} retry={retry} />}
      {feed.phase === "stale" && <div className="notice" role="alert"><TriangleAlert size={17} /><span>Showing last known data. {feed.error}</span><button className="compact" onClick={retry}>Reconnect</button></div>}
      {snapshot && <>
        {allowed("session.warn") && !!activeSelection.length && <div className="notice selection">
          <strong>{activeSelection.length} selected</strong>
          {confirm ? <><span>Send a warning to the selected candidates?</span>
            <button className="primary compact" disabled={warn.isPending || feed.phase !== "live"} onClick={() => { setConfirm(false); warn.mutate(activeSelection); }}>Send warnings</button>
            <button className="compact" onClick={() => setConfirm(false)}>Cancel</button></> :
            <><button className="compact" disabled={warn.isPending || feed.phase !== "live"} onClick={() => setConfirm(true)}>{warn.isPending ? "Sending…" : "Warn selected"}</button>
            <button className="compact" disabled={warn.isPending} onClick={() => setSelected(new Set())}>Clear selection</button></>}
        </div>}
        <div className="panel-feedback"><Feedback error={warn.error} message={warn.data ? `${warn.data.results.length - rejected.length} accepted by the server. ${rejected.length} rejected.` : undefined} />
          {!!rejected.length && <details><summary>Warning failures</summary><ul>{rejected.map((row) => <li key={row.session_id}>{snapshot.sessions.find((session) => session.session_id === row.session_id)?.display_name as string || row.session_id} · {row.error}</li>)}</ul></details>}
        </div>
        <LiveGrid sessions={snapshot.sessions} canWarn={allowed("session.warn") && feed.phase === "live" && !warn.isPending && !confirm} selected={selected} onSelect={toggle} />
      </>}
    </section>
  </main>;
}
