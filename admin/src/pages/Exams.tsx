import React from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Activity, ArrowRight, ChevronLeft, ChevronRight, ClipboardList, Plus, Search, Settings2 } from "lucide-react";
import { api } from "../api/client";
import { usePermissions } from "../auth";
import { Badge, Failure, Feedback, PageHeading, State } from "../components/ui";

export type Exam = { id: string; code: string; title: string; status: string; exam_url?: string | null; exam_url_editable?: boolean };
type ExamList = { items: Exam[]; next_cursor: number; total: number };
const PAGE_SIZE = 50;

function loadExams(signal: AbortSignal, cursor = 0, search = "", status = "") {
  return api<ExamList>(`/api/v1/exams?${new URLSearchParams({ cursor: String(cursor), q: search, status })}`, { signal });
}

export function Exams({ mode }: { mode: "overview" | "exams" | "monitor" }) {
  const [params] = useSearchParams();
  const initialSearch = params.get("q") ?? "";
  return mode === "overview" ? <Overview /> : <ExamDirectory key={`${mode}:${initialSearch}:${params.get("new") ?? ""}`} initialSearch={initialSearch} monitor={mode === "monitor"} />;
}

function Overview() {
  const open = useQuery({ queryKey: ["exams", "open"], queryFn: ({ signal }) => loadExams(signal, 0, "", "OPEN") });
  const drafts = useQuery({ queryKey: ["exams", "drafts"], queryFn: ({ signal }) => loadExams(signal, 0, "", "DRAFT") });
  const allowed = usePermissions();
  const navigate = useNavigate();
  const [query, setQuery] = React.useState("");
  return <main className="overview">
    <h1>Exam operations</h1>
    <form className="overview-search" role="search" aria-label="Overview exam search" onSubmit={(event) => {
      event.preventDefault();
      navigate(query.trim() ? `/exams?q=${encodeURIComponent(query.trim())}` : "/exams");
    }}>
      <label htmlFor="overview-exam-search">Find an exam</label>
      <input id="overview-exam-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by exam title or code" />
      <div className="overview-search-actions">
        <Link className="button compact" to="/exams"><ClipboardList size={15} /> Manage exams</Link>
        <button className="primary compact" type="submit"><Search size={15} /> Search</button>
      </div>
    </form>
    <section className="home-section">
      <div className="home-section-heading"><h2>Open exams <span>{open.data?.total ?? ""}</span></h2>
        {allowed("session.read") && <Link className="text-link" to="/monitor">View monitoring <ArrowRight size={14} /></Link>}</div>
      {open.isPending ? <State title="Loading open exams" kind="loading" /> : open.isError ? <Failure error={open.error} retry={() => void open.refetch()} /> :
        open.data.items.length ? <HomeExamRows exams={open.data.items.slice(0, 5)} monitor={allowed("session.read")} /> :
        <State title="No open exams"><p>Open an exam to start monitoring candidate sessions.</p></State>}
    </section>
    <section className="home-section">
      <div className="home-section-heading"><h2>Draft exams <span>{drafts.data?.total ?? ""}</span></h2><Link className="text-link" to="/exams">View all exams <ArrowRight size={14} /></Link></div>
      {drafts.isPending ? <State title="Loading draft exams" kind="loading" /> : drafts.isError ? <Failure error={drafts.error} retry={() => void drafts.refetch()} /> :
        drafts.data.items.length ? <HomeExamRows exams={drafts.data.items.slice(0, 5)} monitor={false} /> :
        <State title="No drafts"><p>Exams awaiting setup appear here.</p>{allowed("exam.write") && <Link className="button compact" to="/exams?new=1"><Plus size={15} /> New exam</Link>}</State>}
    </section>
  </main>;
}

function HomeExamRows({ exams, monitor }: { exams: Exam[]; monitor: boolean }) {
  return <ul className="home-exam-list">{exams.map((exam) => <li key={exam.id}>
    <Link to={monitor ? `/exams/${exam.id}` : `/exams/${exam.id}/setup`}>
      <span className="home-exam-icon"><ClipboardList size={15} aria-hidden="true" /></span>
      <span className="home-exam-name"><strong>{exam.title}</strong><small>{exam.code}</small></span>
      <Badge value={exam.status} />
      <ChevronRight size={15} aria-hidden="true" />
    </Link>
  </li>)}</ul>;
}

function ExamDirectory({ monitor, initialSearch }: { monitor: boolean; initialSearch: string }) {
  const queryClient = useQueryClient();
  const allowed = usePermissions();
  const [search, setSearch] = React.useState(initialSearch);
  const [params] = useSearchParams();
  const [status, setStatus] = React.useState("");
  const [cursor, setCursor] = React.useState(0);
  const [creating, setCreating] = React.useState(!monitor && allowed("exam.write") && params.get("new") === "1");
  const [code, setCode] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [examUrl, setExamUrl] = React.useState("");
  const [cameraRequired, setCameraRequired] = React.useState(true);
  const [created, setCreated] = React.useState<Exam | null>(null);
  const deferredSearch = React.useDeferredValue(search.trim());
  const exams = useQuery({
    queryKey: ["exams", cursor, deferredSearch, status],
    queryFn: ({ signal }) => loadExams(signal, cursor, deferredSearch, status),
    placeholderData: keepPreviousData,
  });
  const create = useMutation({
    mutationFn: () => api<Exam>("/api/v1/exams", { method: "POST", body: JSON.stringify({ code: code.trim(), title: title.trim(), policy: { camera: cameraRequired, microphone: true, ...(examUrl.trim() ? { exam_url: examUrl.trim() } : {}) } }) }),
    onSuccess: async (exam) => {
      setCreated(exam);
      setCreating(false);
      setCode("");
      setTitle("");
      setCameraRequired(true);
      setExamUrl("");
      setCursor(0);
      setSearch("");
      setStatus("");
      await queryClient.invalidateQueries({ queryKey: ["exams"] });
    },
  });
  return <main>
    <PageHeading title={monitor ? "Monitoring" : "Exams"}
      description={monitor ? "Choose an exam to see its candidate sessions and live status." : "Create exams, configure rosters, and issue candidate enrollment tokens."}
      actions={!monitor && allowed("exam.write") && <button className="primary" onClick={() => { create.reset(); setCreating(true); }} disabled={creating}><Plus size={17} /> New exam</button>} />
    {creating && <section className="panel padded">
      <h2>Create an exam</h2>
      <form onSubmit={(event) => { event.preventDefault(); if (code.trim() && title.trim() && !create.isPending) create.mutate(); }}>
        <div className="form-grid"><label>Exam code<input autoFocus required maxLength={60} value={code} onChange={(event) => setCode(event.target.value)} placeholder="CS101" /></label>
          <label>Exam title<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Introduction to Computer Science" /></label></div>
        <label>Exam link (optional)<input type="url" maxLength={2000} value={examUrl} onChange={(event) => setExamUrl(event.target.value)} placeholder="https://exams.example.edu/..." /></label>
        <label className="exam-camera-check"><input type="checkbox" checked={cameraRequired} onChange={(event) => setCameraRequired(event.target.checked)} /> Require a desktop camera check before starting</label>
        <div className="actions"><button className="primary" disabled={create.isPending || !code.trim() || !title.trim()}>{create.isPending ? "Creating…" : "Create exam"}</button>
          <button type="button" disabled={create.isPending} onClick={() => setCreating(false)}>Cancel</button></div>
        <Feedback error={create.error} />
      </form>
    </section>}
    {created && <p className="feedback" role="status">Created {created.title}. <Link className="text-link" to={`/exams/${created.id}/setup`}>Set up the exam</Link></p>}
    <section className="panel">
      <div className="panel-heading"><div><h2>{monitor ? "Exam sessions" : "Exam directory"}</h2><p>{exams.data && !exams.isPlaceholderData ? `${exams.data.total} matching ${exams.data.total === 1 ? "exam" : "exams"}` : "Browse exams in your workspace"}</p></div></div>
      <div className="table-toolbar">
        <label className="search-box"><Search size={17} /><input aria-label="Search exams" value={search} placeholder="Search by title or code" onChange={(event) => { setSearch(event.target.value); setCursor(0); }} /></label>
        <label className="inline-label">Status <select value={status} onChange={(event) => { setStatus(event.target.value); setCursor(0); }}><option value="">All statuses</option><option value="DRAFT">Draft</option><option value="OPEN">Open</option><option value="CLOSED">Closed</option><option value="ARCHIVED">Archived</option></select></label>
      </div>
      {exams.isPending || exams.isPlaceholderData ? <State title="Loading exams" kind="loading" /> : exams.isError ? <Failure error={exams.error} retry={() => void exams.refetch()} /> :
        exams.data.items.length ? <ExamRows exams={exams.data.items} monitor={monitor} /> :
        <State title={deferredSearch || status ? "No matching exams" : "No exams yet"} icon={ClipboardList}>
          {deferredSearch || status ? <p>Try a different title, code, or status.</p> : <p>Created exams will appear here.</p>}
        </State>}
      {!!exams.data && !exams.isPlaceholderData && (cursor > 0 || exams.data.next_cursor < exams.data.total) && <div className="pagination">
        <span>Page {Math.floor(cursor / PAGE_SIZE) + 1}</span><div className="actions">
          <button disabled={!cursor} onClick={() => setCursor(Math.max(0, cursor - PAGE_SIZE))}><ChevronLeft size={16} /> Previous</button>
          <button disabled={exams.data.next_cursor >= exams.data.total} onClick={() => setCursor(exams.data.next_cursor)}>Next <ChevronRight size={16} /></button>
        </div>
      </div>}
    </section>
  </main>;
}

function ExamRows({ exams, monitor }: { exams: Exam[]; monitor: boolean }) {
  return <div className="table-scroll"><table>
    <thead><tr><th>Exam</th><th className="exam-code-column">Code</th><th>Status</th><th><span className="sr-only">Action</span></th></tr></thead>
    <tbody>{exams.map((exam) => <tr key={exam.id}>
      <td className="table-title"><Link to={monitor ? `/exams/${exam.id}` : `/exams/${exam.id}/setup`}>{exam.title}</Link><span className="code exam-code-mobile">{exam.code}</span></td>
      <td className="exam-code-column"><span className="code">{exam.code}</span></td><td><Badge value={exam.status} /></td>
      <td className="table-action"><Link className="button compact" to={monitor ? `/exams/${exam.id}` : `/exams/${exam.id}/setup`}>
        {monitor ? <Activity size={16} /> : <Settings2 size={16} />} {monitor ? "Monitor" : "Set up"}
      </Link></td>
    </tr>)}</tbody>
  </table></div>;
}
