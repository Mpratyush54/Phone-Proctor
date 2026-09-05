import React from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export function ExamSetup({ embedded, onChanged }: { embedded?: boolean; onChanged?: () => void | Promise<unknown> }) {
  const { id: paramId = "" } = useParams();
  const id = paramId;
  const [csv, setCsv] = React.useState("student_external_id,display_name\ns1,Ada");
  const [note, setNote] = React.useState("");
  async function afterChange() {
    if (onChanged) await onChanged();
  }
  const body = (
    <>
      <div className="toolbar">
        <button onClick={() => api(`/api/v1/exams/${id}/open`, { method: "POST", body: "{}" }).then(afterChange).then(() => setNote("Exam opened"))}>
          Open exam
        </button>
      </div>
      <h2>Roster CSV</h2>
      <textarea rows={4} style={{ width: "100%" }} value={csv} onChange={(e) => setCsv(e.target.value)} />
      <div className="toolbar">
        <button
          className="ghost"
          onClick={async () => {
            const rows = csv
              .trim()
              .split("\n")
              .slice(1)
              .map((line) => {
                const [student_external_id, display_name] = line.split(",");
                return { student_external_id, display_name };
              });
            const r = await api(`/api/v1/exams/${id}/roster`, { method: "POST", body: JSON.stringify({ rows }) });
            setNote(`Imported: ${(r.results || []).filter((x: { ok: boolean }) => x.ok).length}/${(r.results || []).length} ok`);
            await afterChange();
          }}
        >
          Import roster
        </button>
      </div>
      {note && <p className="muted">{note}</p>}
    </>
  );
  if (embedded) return body;
  return (
    <>
      <div className="pagehead"><h1>Exam setup</h1></div>
      <div className="card">{body}</div>
    </>
  );
}
