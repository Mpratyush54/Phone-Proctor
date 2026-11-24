import React from "react";
import { Camera, ChevronLeft, ChevronRight, Radio, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge, State } from "./ui";
import type { SessionSummary } from "../stream";

const PAGE_SIZE = 24;

export function LiveGrid({ sessions, canWarn, selected, onSelect }: {
  sessions: SessionSummary[]; canWarn: boolean; selected: Set<string>; onSelect: (id: string) => void;
}) {
  const [search, setSearch] = React.useState("");
  const [filter, setFilter] = React.useState("all");
  const [page, setPage] = React.useState(0);
  const items = React.useMemo(() => {
    const query = search.trim().toLowerCase();
    return sessions.filter((session) => {
      const matchesSearch = !query || String(session.display_name ?? "").toLowerCase().includes(query) || session.session_id.toLowerCase().includes(query);
      const needsAttention = session.connectivity !== "online" || ["BLOCKED", "DEGRADED"].includes(String(session.lifecycle));
      return matchesSearch && (filter === "all" || (filter === "online" ? session.connectivity === "online" : needsAttention));
    }).sort((first, second) => Number(second.lifecycle === "BLOCKED") - Number(first.lifecycle === "BLOCKED"));
  }, [sessions, search, filter]);
  const lastPage = Math.max(0, Math.ceil(items.length / PAGE_SIZE) - 1);
  const shownPage = Math.min(page, lastPage);
  const shown = items.slice(shownPage * PAGE_SIZE, (shownPage + 1) * PAGE_SIZE);
  if (!sessions.length) return <State title="No candidate sessions yet" icon={Radio}><p>Sessions appear here after candidates redeem their enrollment tokens.</p></State>;
  return <>
    <div className="table-toolbar">
      <label className="search-box"><Search size={17} /><input aria-label="Search candidate sessions" placeholder="Search by name or session ID" value={search}
        onChange={(event) => { setSearch(event.target.value); setPage(0); }} /></label>
      <label className="inline-label">Show <select value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0); }}>
        <option value="all">All candidates</option><option value="attention">Needs attention</option><option value="online">Online</option>
      </select></label>
    </div>
    {!shown.length ? <State title="No matching sessions"><p>Change the search or connectivity filter.</p></State> :
      <ul className="session-grid">{shown.map((session) => {
        const name = String(session.display_name || session.session_id);
        const selectable = canWarn && session.connectivity === "online" && session.lifecycle !== "ENDED";
        return <li className="session-card" key={session.session_id}>
          <div className="section-line">
            <Link className="session-title" title={name} to={`/sessions/${session.session_id}`}>{name}</Link>
            {selectable && <input type="checkbox" aria-label={`Select ${name}`} checked={selected.has(session.session_id)} onChange={() => onSelect(session.session_id)} />}
          </div>
          <div className="session-badges"><Badge value={typeof session.lifecycle === "string" ? session.lifecycle : undefined} /><Badge value={typeof session.connectivity === "string" ? session.connectivity : undefined} /></div>
          <span className="session-media"><Camera size={15} />{session.thumbnail_available ? "Thumbnail available" : "No thumbnail"}</span>
        </li>;
      })}</ul>}
    {!!items.length && <div className="pagination"><span>Showing {shownPage * PAGE_SIZE + 1}–{shownPage * PAGE_SIZE + shown.length} of {items.length}</span>
      <div className="actions"><button disabled={!shownPage} onClick={() => setPage(shownPage - 1)}><ChevronLeft size={16} /> Previous</button>
      <button disabled={shownPage === lastPage} onClick={() => setPage(shownPage + 1)}>Next <ChevronRight size={16} /></button></div></div>}
  </>;
}
