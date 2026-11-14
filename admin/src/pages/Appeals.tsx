import React from "react";
import { api } from "../api/client";

export function Appeals() {
  const [findingId, setFindingId] = React.useState("");
  const [originalReviewerId, setOriginalReviewerId] = React.useState("");
  const [appealReviewerId, setAppealReviewerId] = React.useState("");
  const [sessionId, setSessionId] = React.useState("");
  const [out, setOut] = React.useState("");
  return (
    <main>
      <h1>Appeals</h1>
      <p>Evidence freeze and independent appeal. Appeal reviewer cannot be the original decision maker.</p>
      <h2>Freeze evidence</h2>
      <input placeholder="session id" value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
      <button
        onClick={async () => {
          try {
            const r = await api(`/api/v1/sessions/${sessionId}/legal-hold`, { method: "POST", body: "{}" });
            setOut(JSON.stringify(r, null, 2));
          } catch (e) {
            setOut(JSON.stringify(e));
          }
        }}
      >
        Freeze
      </button>
      <h2>Appeal finding</h2>
      <input placeholder="finding id" value={findingId} onChange={(e) => setFindingId(e.target.value)} />
      <input placeholder="original reviewer id" value={originalReviewerId} onChange={(e) => setOriginalReviewerId(e.target.value)} />
      <input placeholder="appeal reviewer id" value={appealReviewerId} onChange={(e) => setAppealReviewerId(e.target.value)} />
      <button
        onClick={async () => {
          try {
            const r = await api(`/api/v1/findings/${findingId}/appeal`, {
              method: "POST",
              body: JSON.stringify({ original_reviewer_id: originalReviewerId, appeal_reviewer_id: appealReviewerId }),
            });
            setOut(JSON.stringify(r, null, 2));
          } catch (e) {
            setOut(JSON.stringify(e));
          }
        }}
      >
        Submit appeal
      </button>
      <pre>{out}</pre>
    </main>
  );
}
