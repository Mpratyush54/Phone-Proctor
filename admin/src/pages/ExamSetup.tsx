import React from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export function ExamSetup({ embedded, onChanged }: { embedded?: boolean; onChanged?: () => void | Promise<unknown> }) {
  const { id: paramId = "" } = useParams();
  const id = paramId;
  const [csv, setCsv] = React.useState("student_external_id,display_name\ns1,Ada");
  async function afterChange() {
    if (onChanged) await onChanged();
  }
  const body = (
    <>
      <button onClick={() => api(`/api/v1/exams/${id}/open`, { method: "POST", body: "{}" }).then(afterChange)}>Open exam</button>
      <h2>Roster CSV</h2>
      <textarea rows={4} cols={60} value={csv} onChange={(e) => setCsv(e.target.value)} />
      <button
        onClick={async () => {
          const rows = csv
            .trim()
            .split("\n")
            .slice(1)
            .map((line) => {
              const [student_external_id, display_name] = line.split(",");
              return { student_external_id, display_name };
            });
          await api(`/api/v1/exams/${id}/roster`, { method: "POST", body: JSON.stringify({ rows }) });
          await afterChange();
        }}
      >
        Import
      </button>
    </>
  );
  if (embedded) return body;
  return (
    <main>
      <h1>Exam setup</h1>
      {body}
    </main>
  );
}
