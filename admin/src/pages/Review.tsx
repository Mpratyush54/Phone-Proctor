import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronLeft, ChevronRight, ScanEye } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { usePermissions } from "../auth";
import { Badge, Failure, PageHeading, State } from "../components/ui";

type Queue = { items: { id: string; label: string; status: string; event_seq?: number }[]; next_cursor: number; total: number };

export function Review() {
  const allowed = usePermissions();
  const [pages, setPages] = React.useState([0]);
  const cursor = pages[pages.length - 1];
  const review = useQuery({
    queryKey: ["review", cursor],
    queryFn: ({ signal }) => api<Queue>(`/api/v1/review/queue?cursor=${cursor}`, { signal }),
  });
  return <main>
    <PageHeading title="Evidence review" description="Review recorded observations from candidate sessions."
      actions={allowed("session.read") && <Link className="button" to="/monitor">Go to monitoring <ArrowRight size={17} /></Link>} />
    <section className="panel">
      <div className="panel-heading"><div><h2>Recorded findings</h2><p>{review.data ? `${review.data.total} findings in this workspace` : "Workspace findings"}</p></div></div>
      {review.isPending ? <State kind="loading" title="Loading findings" /> : review.isError ? <Failure error={review.error} retry={() => void review.refetch()} /> :
        !review.data.items.length ? <State title="No findings recorded" icon={ScanEye}><p>Add a finding to an event from its candidate session.</p></State> :
        <div className="table-scroll"><table><thead><tr><th>Observation</th><th>Status</th><th>Finding reference</th>{allowed("appeal.decide") && <th><span className="sr-only">Appeal</span></th>}</tr></thead>
          <tbody>{review.data.items.map((item) => <tr key={item.id}><td className="table-title">{item.label}{item.event_seq !== undefined && <div className="muted">Event {item.event_seq}</div>}</td><td><Badge value={item.status} /></td>
            <td className="code">{item.id}</td>{allowed("appeal.decide") && <td className="table-action"><Link className="button compact" to={`/appeals?finding=${item.id}`}>Open appeal</Link></td>}
          </tr>)}</tbody></table></div>}
      {review.data && (cursor > 0 || review.data.next_cursor < review.data.total) && <div className="pagination"><span>Page {pages.length}</span><div className="actions">
        <button disabled={pages.length === 1} onClick={() => setPages(pages.slice(0, -1))}><ChevronLeft size={16} /> Previous</button>
        <button disabled={review.data.next_cursor >= review.data.total} onClick={() => setPages([...pages, review.data!.next_cursor])}>Next <ChevronRight size={16} /></button>
      </div></div>}
    </section>
  </main>;
}
