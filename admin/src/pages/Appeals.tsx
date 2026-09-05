import React from "react";
import { api } from "../api/client";

export function Appeals() {
  const [findingId, setFindingId] = React.useState("");
  const [originalReviewerId, setOriginalReviewerId] = React.useState("");
  const [appealReviewerId, setAppealReviewerId] = React.useState("");
  const [sessionId, setSessionId] = React.useState("");
  const [out, setOut] = React.useState("");
  return (
    <>
      <div className="pagehead">
        <h1>Appeals</h1>
        <p className="muted">Evidence freeze and independent appeal. The appeal reviewer cannot be the original decision maker.</p>
      </div>
      <div className="card">
        <h3>Freeze evidence</h3>
        <div className="toolbar">
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
        </div>
      </div>
      <div className="card">
        <h3>Appeal finding</h3>
        <label>Finding id</label>
        <input placeholder="finding id" value={findingId} onChange={(e) => setFindingId(e.target.value)} />
        <label>Original reviewer id</label>
        <input placeholder="original reviewer id" value={originalReviewerId} onChange={(e) => setOriginalReviewerId(e.target.value)} />
        <label>Appeal reviewer id</label>
        <input placeholder="appeal reviewer id" value={appealReviewerId} onChange={(e) => setAppealReviewerId(e.target.value)} />
        <div className="toolbar">
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
        </div>
      </div>
      {out && <pre className="dump">{out}</pre>}
    </>
  );
}
