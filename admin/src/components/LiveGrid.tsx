import { Link } from "react-router-dom";
import type { Snapshot } from "../stream";

export function LiveGrid({ sessions }: { sessions: Snapshot["sessions"] }) {
  return (
    <>
      <h2>Live grid</h2>
      <div className="grid">
        {sessions.map((s) => (
          <Link className="cell" key={s.session_id} to={`/sessions/${s.session_id}`}>
            <div>{String(s.display_name || s.session_id)}</div>
            <div>{String(s.lifecycle)} / {String(s.connectivity)}</div>
            <div>thumb: {String(s.thumbnail_available)}</div>
          </Link>
        ))}
      </div>
    </>
  );
}
