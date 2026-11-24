import React from "react";
import { useMutation } from "@tanstack/react-query";
import { Archive, Gavel, Shield } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { usePermissions } from "../auth";
import { Feedback, PageHeading } from "../components/ui";

export function Appeals() {
  const allowed = usePermissions();
  const [params] = useSearchParams();
  const [findingId, setFindingId] = React.useState(params.get("finding") ?? "");
  const [appealReviewerId, setAppealReviewerId] = React.useState("");
  const [sessionId, setSessionId] = React.useState("");
  const freeze = useMutation({
    mutationFn: () => api(`/api/v1/sessions/${encodeURIComponent(sessionId.trim())}/legal-hold`, { method: "POST", body: "{}" }),
  });
  const stepUp = useMutation({
    mutationFn: () => api("/api/v1/auth/step-up", { method: "POST", body: "{}" }),
    onSuccess: () => freeze.reset(),
  });
  const appeal = useMutation({
    mutationFn: () => api<{ id: string }>(`/api/v1/findings/${encodeURIComponent(findingId.trim())}/appeal`, {
      method: "POST", body: JSON.stringify({ appeal_reviewer_id: appealReviewerId.trim() }),
    }),
  });
  const needsVerification = freeze.error instanceof ApiError && freeze.error.code === "STEP_UP_REQUIRED";
  return <main>
    <PageHeading title="Appeals" description="Protect session evidence and assign an independent appeal reviewer." />
    {allowed("exam.end") && <section className="panel padded">
      <h2 className="heading-icon"><Archive size={19} /> Freeze session evidence</h2>
      <form onSubmit={(event) => { event.preventDefault(); if (sessionId.trim() && !freeze.isPending && !stepUp.isPending) freeze.mutate(); }}>
        <label>Session ID<input required disabled={freeze.isPending} value={sessionId} onChange={(event) => { setSessionId(event.target.value); freeze.reset(); }} /></label>
        <button disabled={freeze.isPending || stepUp.isPending || !sessionId.trim()}>{freeze.isPending ? "Freezing…" : "Freeze evidence"}</button>
      </form>
      <Feedback error={freeze.error} message={freeze.isSuccess ? "Evidence hold applied." : undefined} />
      {needsVerification && <button onClick={() => stepUp.mutate()} disabled={stepUp.isPending}><Shield size={16} /> {stepUp.isPending ? "Confirming…" : "Confirm development session"}</button>}
      <Feedback error={stepUp.error} message={stepUp.isSuccess ? "Staff session confirmed. You can place the hold now." : undefined} />
    </section>}
    <section className="panel padded">
      <h2 className="heading-icon"><Gavel size={19} /> Submit an appeal</h2>
      <p className="muted">Choose a staff member in this workspace. The server checks that they did not record the original finding.</p>
      <form onSubmit={(event) => { event.preventDefault(); if (findingId.trim() && appealReviewerId.trim() && !appeal.isPending) appeal.mutate(); }}>
        <div className="form-grid">
          <label>Finding ID<input required disabled={appeal.isPending} value={findingId} onChange={(event) => { setFindingId(event.target.value); appeal.reset(); }} /></label>
          <label>Appeal reviewer ID<input required disabled={appeal.isPending} value={appealReviewerId} onChange={(event) => { setAppealReviewerId(event.target.value); appeal.reset(); }} /></label>
        </div>
        <button className="primary" disabled={appeal.isPending || !findingId.trim() || !appealReviewerId.trim()}>{appeal.isPending ? "Submitting…" : "Submit appeal"}</button>
      </form>
      <Feedback error={appeal.error} message={appeal.data ? `Appeal submitted. Reference ${appeal.data.id}.` : undefined} />
    </section>
  </main>;
}
