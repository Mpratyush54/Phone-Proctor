import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Activity, ArrowLeft, ClipboardList, Copy, KeyRound, Upload } from "lucide-react";
import { api } from "../api/client";
import { usePermissions } from "../auth";
import { Badge, Failure, Feedback, PageHeading, State } from "../components/ui";
import type { Exam } from "./Exams";

type Enrollment = { id: string; studentExternalId: string; displayName: string };
type Roster = { items: Enrollment[]; next_cursor: number; total: number };
type ImportResult = { ok: boolean; student_external_id: string; error?: string };
const PAGE = 100;

function parseRoster(csv: string) {
  const records: string[][] = [];
  const linePattern = /^(?:"((?:[^"]|"")*)"|([^",]*)),(?:"((?:[^"]|"")*)"|([^",]*))$/;
  for (const line of csv.trim().split(/\r?\n/)) {
    if (!line.trim()) continue;
    const result = line.trim().match(linePattern);
    if (!result) throw new Error("Each CSV row needs a student ID and a display name. Use double quotes around values containing commas.");
    records.push([(result[1] ?? result[2]).replaceAll('""', '"').trim(), (result[3] ?? result[4]).replaceAll('""', '"').trim()]);
  }
  const header = records.shift();
  if (header?.[0] !== "student_external_id" || header[1] !== "display_name") throw new Error("Start the CSV with student_external_id,display_name.");
  if (!records.length || records.some((row) => !row[0] || !row[1])) throw new Error("Add at least one row with both a student ID and a name.");
  return records.map(([student_external_id, display_name]) => ({ student_external_id, display_name }));
}

export function ExamSetup() {
  const { id = "" } = useParams();
  return <Setup key={id} id={id} />;
}

function Setup({ id }: { id: string }) {
  const allowed = usePermissions();
  const [csv, setCsv] = React.useState("");
  const [editedLink, setEditedLink] = React.useState<string>();
  const [cursor, setCursor] = React.useState(0);
  const [token, setToken] = React.useState<{ name: string; value: string } | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [copyError, setCopyError] = React.useState<unknown>();
  const queryClient = useQueryClient();
  const exam = useQuery({ queryKey: ["exam", id], queryFn: ({ signal }) => api<Exam>(`/api/v1/exams/${id}`, { signal }) });
  const roster = useQuery({ queryKey: ["roster", id, cursor], enabled: exam.isSuccess && allowed("roster.import"),
    queryFn: ({ signal }) => api<Roster>(`/api/v1/exams/${id}/roster?cursor=${cursor}`, { signal }) });
  const saveLink = useMutation({
    mutationFn: (url: string | null) => api<Exam>(`/api/v1/exams/${id}/exam-link`, { method: "PATCH", body: JSON.stringify({ url }) }),
    onSuccess: (data) => { queryClient.setQueryData(["exam", id], data); setEditedLink(undefined); },
  });
  const open = useMutation({
    mutationFn: () => api<Exam>(`/api/v1/exams/${id}/open`, { method: "POST", body: "{}" }),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["exam", id] }), queryClient.invalidateQueries({ queryKey: ["exams"] })]);
    },
  });
  const importRoster = useMutation({
    mutationFn: () => api<{ results: ImportResult[] }>(`/api/v1/exams/${id}/roster`, { method: "POST", body: JSON.stringify({ rows: parseRoster(csv) }) }),
    onSuccess: async (data) => {
      if (data.results.every((item) => item.ok)) setCsv("");
      setCursor(0);
      await queryClient.invalidateQueries({ queryKey: ["roster", id] });
    },
  });
  const issue = useMutation({
    mutationFn: (row: Enrollment) => api<{ token: string }>(`/api/v1/enrollments/${row.id}/token`, { method: "POST", body: "{}" }),
    onSuccess: (data, row) => { setToken({ name: row.displayName, value: data.token }); setCopied(false); setCopyError(undefined); },
  });
  if (exam.isPending) return <main><State title="Loading exam setup" kind="loading" /></main>;
  if (exam.isError) return <main><Failure title="Exam setup is unavailable" error={exam.error} retry={() => void exam.refetch()} /></main>;
  const linkInput = editedLink ?? exam.data.exam_url ?? "";
  const errors = importRoster.data?.results.filter((result) => !result.ok) ?? [];
  return <main>
    <Link className="back-link" to="/exams"><ArrowLeft size={16} /> Exams</Link>
    <PageHeading title={exam.data.title} description={`${exam.data.code} · Exam setup`} actions={allowed("session.read") && <Link className="button" to={`/exams/${id}`}><Activity size={17} /> Open monitoring</Link>} />
    <section className="panel padded">
      <h2>Exam website</h2>
      <p className="muted">Students see this website inside Phone-Proctor after staff start their session.</p>
      {allowed("exam.write") && exam.data.exam_url_editable ? <form onSubmit={(event) => {
        event.preventDefault();
        if (!saveLink.isPending) saveLink.mutate(linkInput.trim() || null);
      }}>
        <label>Website address<input type="url" value={linkInput} maxLength={2000} placeholder="https://exams.example.edu/assessment"
          onChange={(event) => { setEditedLink(event.target.value); saveLink.reset(); }} disabled={saveLink.isPending} /></label>
        <button disabled={saveLink.isPending || linkInput.trim() === (exam.data.exam_url ?? "")}>{saveLink.isPending ? "Saving…" : "Save website"}</button>
      </form> : <p>{exam.data.exam_url ?? "No website assigned."}</p>}
      {!exam.data.exam_url_editable && <p className="muted">The website is locked after a candidate enrolls.</p>}
      <Feedback error={saveLink.error} message={saveLink.isSuccess ? "Exam website saved." : undefined} />
    </section>
    <section className="panel padded">
      <div className="section-line"><div><h2>Enrollment</h2><p className="muted">Open enrollment before starting a session from Monitoring.</p></div><Badge value={exam.data.status} /></div>
      {allowed("exam.write") && exam.data.status === "DRAFT" && <button className="primary" disabled={open.isPending} onClick={() => open.mutate()}>{open.isPending ? "Opening…" : "Open enrollment"}</button>}
      <Feedback error={open.error} message={open.isSuccess ? "Enrollment is open." : undefined} />
    </section>
    {allowed("roster.import") && <>
      <section className="panel padded">
        <h2>Import roster</h2><p className="muted">Paste a CSV with student IDs and display names.</p>
        <form onSubmit={(event) => { event.preventDefault(); if (csv.trim() && !importRoster.isPending) importRoster.mutate(); }}>
          <label>Roster CSV<textarea value={csv} onChange={(event) => setCsv(event.target.value)} rows={5} placeholder={"student_external_id,display_name\ns01,Ada Patel"} /></label>
          <button disabled={!csv.trim() || importRoster.isPending}><Upload size={16} />{importRoster.isPending ? "Importing…" : "Import candidates"}</button>
        </form>
        <Feedback error={importRoster.error} message={importRoster.data ? `${importRoster.data.results.length - errors.length} imported. ${errors.length} rejected.` : undefined} />
        {!!errors.length && <details><summary>Rejected rows</summary><ul>{errors.map((error, index) => <li key={index}>{error.student_external_id} · {error.error}</li>)}</ul></details>}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><h2>Candidate roster</h2><p>{roster.data ? `${roster.data.total} enrolled candidates` : "Issue tokens for individual candidates."}</p></div></div>
        <div className="panel-feedback"><Feedback error={issue.error} />
        {token && <div className="token-card"><p className="muted">Have the candidate paste this token into the Phone-Proctor student desktop and select Join exam.</p><label>Enrollment token for {token.name}<input readOnly value={token.value} onFocus={(event) => event.target.select()} /></label><div className="actions">
          <button onClick={async () => {
            try { await navigator.clipboard.writeText(token.value); setCopied(true); setCopyError(undefined); }
            catch { setCopyError(new Error("Clipboard is unavailable. Select and copy the token above.")); }
          }}><Copy size={15} /> {copied ? "Copied" : "Copy token"}</button><button onClick={() => setToken(null)}>Hide token</button>
        </div><Feedback error={copyError} /></div>}</div>
        {roster.isPending ? <State kind="loading" title="Loading roster" /> : roster.isError ? <Failure error={roster.error} retry={() => void roster.refetch()} /> :
          roster.data.items.length === 0 ? <State title="No candidates imported" icon={ClipboardList}><p>Import a roster to issue enrollment tokens.</p></State> :
          <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Student ID</th><th><span className="sr-only">Enrollment</span></th></tr></thead>
            <tbody>{roster.data.items.map((row) => <tr key={row.id}><td className="table-title">{row.displayName}</td><td className="code">{row.studentExternalId}</td>
              <td className="table-action"><button className="compact" disabled={issue.isPending} onClick={() => { setToken(null); issue.mutate(row); }}><KeyRound size={15} />{issue.isPending && issue.variables?.id === row.id ? "Issuing…" : "Issue token"}</button></td>
            </tr>)}</tbody></table></div>}
        {roster.data && (cursor > 0 || roster.data.next_cursor < roster.data.total) && <div className="pagination"><span>Page {Math.floor(cursor / PAGE) + 1}</span><div className="actions">
          <button disabled={!cursor} onClick={() => setCursor(Math.max(0, cursor - PAGE))}>Previous</button>
          <button disabled={roster.data.next_cursor >= roster.data.total} onClick={() => setCursor(roster.data!.next_cursor)}>Next</button>
        </div></div>}
      </section>
    </>}
  </main>;
}
