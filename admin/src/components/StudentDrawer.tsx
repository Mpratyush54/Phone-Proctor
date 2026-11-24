import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Activity, ArrowLeft, ClipboardCheck, Flag, Radio, Shield, TriangleAlert } from "lucide-react";
import { api, ApiError } from "../api/client";
import { StaffContext, usePermissions } from "../auth";
import { Badge, Failure, Feedback, PageHeading, State } from "./ui";

type SessionDetail = {
  session: { id: string; examId: string; observed: string; desired: string; connectivity: string; display_name?: string; claimOwner?: string; claimUntil?: number };
  commands: { id: string; type: string; status: string; createdAt: number }[];
  events: { seq: number; payload: unknown }[];
  health: { connectivity: string; attention: string };
};
const lifecycleActions = [
  { type: "EXAM_START", label: "Start session", permission: "session.command", states: ["READY", "DEGRADED"] },
  { type: "EXAM_PAUSE", label: "Pause session", permission: "session.command", states: ["IN_EXAM"] },
  { type: "EXAM_RESUME", label: "Resume session", permission: "session.command", states: ["PAUSED"] },
  { type: "EXAM_END", label: "End session", permission: "exam.end", states: ["READY", "DEGRADED", "IN_EXAM", "PAUSED", "BLOCKED"] },
];

export function StudentDrawer() {
  const { id = "" } = useParams();
  return <Session key={id} id={id} />;
}

function labelFor(type: string) {
  return lifecycleActions.find((item) => item.type === type)?.label ?? (type === "WARN" ? "Send warning" : type.replaceAll("_", " "));
}

function eventLabel(payload: unknown) {
  if (payload && typeof payload === "object" && "event_type" in payload && typeof payload.event_type === "string") {
    return payload.event_type.replaceAll("_", " ");
  }
  return "Agent event";
}

function Session({ id }: { id: string }) {
  const allowed = usePermissions();
  const staff = React.useContext(StaffContext);
  const client = useQueryClient();
  const [confirm, setConfirm] = React.useState<string | null>(null);
  const [annotation, setAnnotation] = React.useState<{ seq: number; label: string } | null>(null);
  const queryKey = ["session", id];
  const detail = useQuery({
    queryKey,
    queryFn: ({ signal }) => api<SessionDetail>(`/api/v1/sessions/${id}`, { signal }),
    refetchInterval: 2_000,
  });
  const action = useMutation({
    mutationFn: (type: string) => type === "claim"
      ? api(`/api/v1/sessions/${id}/claim`, { method: "POST", body: "{}" })
      : api(`/api/v1/sessions/${id}/commands`, { method: "POST", body: JSON.stringify({ type, idempotency_key: crypto.randomUUID() }) }),
    onSuccess: () => client.invalidateQueries({ queryKey }),
  });
  const stepUp = useMutation({
    mutationFn: () => api("/api/v1/auth/step-up", { method: "POST", body: "{}" }),
    onSuccess: () => { action.reset(); },
  });
  const finding = useMutation({
    mutationFn: ({ seq, label }: { seq: number; label: string }) => api(`/api/v1/sessions/${id}/findings`, {
      method: "POST", body: JSON.stringify({ event_seq: seq, label: label.trim() }),
    }),
    onSuccess: () => { setAnnotation(null); void client.invalidateQueries({ queryKey: ["review"] }); },
  });

  if (detail.isPending) return <main><State title="Loading candidate session" kind="loading" /></main>;
  if (!detail.data) return <main><Failure title="Candidate session is unavailable" error={detail.error} retry={() => void detail.refetch()} /></main>;
  const { session, commands, events, health } = detail.data;
  const pending = commands.some((receipt) => ["accepted", "dispatched"].includes(receipt.status));
  const canControl = !detail.isError && session.connectivity === "online" && !pending && !action.isPending;
  const claim = session.claimOwner && (session.claimUntil ?? 0) > Date.now()
    ? session.claimOwner === staff?.user_id ? "Claimed by you" : "Claimed by another staff member"
    : "Unclaimed";
  const canEnd = action.error instanceof ApiError && action.error.code === "STEP_UP_REQUIRED";
  return <main>
    <Link className="back-link" to={`/exams/${session.examId}`}><ArrowLeft size={16} /> Exam monitoring</Link>
    <PageHeading title={session.display_name || "Candidate session"} description={session.id}
      actions={<button onClick={() => void detail.refetch()} disabled={detail.isFetching}><Radio size={16} />{detail.isFetching ? "Refreshing…" : "Refresh"}</button>} />
    {detail.isError && <div className="notice" role="alert"><TriangleAlert size={17} /> Updates interrupted. Showing last known session data.</div>}
    <div className="overview-stats monitoring-stats">
      <div className="stat"><span className="feature-icon"><Activity size={19} /></span><span>Observed state<strong className="stat-status"><Badge value={session.observed} /></strong></span></div>
      <div className="stat"><span className="feature-icon mint"><Radio size={19} /></span><span>Connectivity<strong className="stat-status"><Badge value={health.connectivity} /></strong></span></div>
      <div className="stat"><span className="feature-icon gold"><Flag size={19} /></span><span>Attention<strong className="stat-status"><Badge value={health.attention} /></strong></span></div>
    </div>
    <section className="panel padded">
      <div className="section-line"><div><h2>Session controls</h2><p className="muted">Requested state: {session.desired.replaceAll("_", " ").toLowerCase()}. The observed state updates after agent confirmation.</p><p className="muted">{claim}</p></div></div>
      <div className="actions">
        {lifecycleActions.filter((item) => allowed(item.permission) && item.states.includes(session.observed)).map((item) =>
          <button key={item.type} disabled={!canControl || !!confirm} onClick={() => { stepUp.reset(); action.reset(); setConfirm(item.type); }}>{item.label}</button>)}
        {allowed("session.warn") && session.observed !== "ENDED" && <button disabled={!canControl || !!confirm} onClick={() => { stepUp.reset(); action.reset(); setConfirm("WARN"); }}><TriangleAlert size={16} /> Warn</button>}
        {allowed("assignment.claim") && <button disabled={detail.isError || action.isPending || !!confirm} onClick={() => action.mutate("claim")}><ClipboardCheck size={16} /> {claim === "Claimed by you" ? "Renew claim" : "Claim session"}</button>}
      </div>
      {confirm && <div className="notice"><strong>{labelFor(confirm)}?</strong><button className="compact primary" disabled={!canControl} onClick={() => { action.mutate(confirm); setConfirm(null); }}>Confirm</button><button className="compact" onClick={() => setConfirm(null)}>Cancel</button></div>}
      <Feedback error={action.error} message={action.isSuccess ? action.variables === "claim" ? "Session claimed." : "Command accepted. Follow its receipt below." : undefined} />
      {canEnd && <button onClick={() => stepUp.mutate()} disabled={stepUp.isPending}><Shield size={16} /> {stepUp.isPending ? "Confirming…" : "Confirm development session"}</button>}
      <Feedback error={stepUp.error} message={stepUp.isSuccess ? "Staff session confirmed. You can submit the command again." : undefined} />
      {pending && <p className="muted">Waiting for the agent to acknowledge a command.</p>}
      {!pending && health.connectivity !== "online" && <p className="muted">A connected candidate agent is needed for commands.</p>}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><h2>Recent activity</h2><p>Latest events received from the candidate agent.</p></div></div>
      <div className="panel-feedback"><Feedback error={finding.error} message={finding.isSuccess ? "Finding recorded for review." : undefined} /></div>
      {!events.length ? <State title="No events received"><p>Events will appear as the agent sends monitoring data.</p></State> :
        <ul className="activity-list">{events.slice().reverse().map((event) => <li key={event.seq}>
          <details><summary><strong>{eventLabel(event.payload)}</strong> <span className="muted">Event {event.seq}</span></summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details>
          {allowed("review.annotate") && <button className="compact" disabled={finding.isPending} onClick={() => { finding.reset(); setAnnotation({ seq: event.seq, label: "" }); }}>Add finding</button>}
          {annotation?.seq === event.seq && <form className="annotation-form" onSubmit={(e) => { e.preventDefault(); if (annotation.label.trim() && !finding.isPending) finding.mutate(annotation); }}>
            <label>Observation<input required maxLength={200} value={annotation.label} onChange={(e) => setAnnotation({ seq: event.seq, label: e.target.value })} /></label>
            <button className="primary compact" disabled={!annotation.label.trim() || finding.isPending}>{finding.isPending ? "Saving…" : "Save finding"}</button>
            <button type="button" className="compact" onClick={() => setAnnotation(null)} disabled={finding.isPending}>Cancel</button>
          </form>}
        </li>)}</ul>}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><h2>Command receipts</h2><p>Delivery and acknowledgement are tracked by the server.</p></div></div>
      {!commands.length ? <State title="No commands sent" /> :
        <div className="table-scroll"><table><thead><tr><th>Command</th><th>Requested</th><th>Receipt</th></tr></thead>
          <tbody>{commands.slice(-50).reverse().map((receipt) => <tr key={receipt.id}><td className="table-title">{labelFor(receipt.type)}</td><td>{new Date(receipt.createdAt).toLocaleString()}</td><td><Badge value={receipt.status} /></td></tr>)}</tbody>
        </table></div>}
    </section>
  </main>;
}
