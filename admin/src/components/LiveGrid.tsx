import { Link } from "react-router-dom";
import type { Snapshot } from "../stream";

type Session = Snapshot["sessions"][number];

function connClass(s: Session): string {
  const c = String(s.connectivity || "");
  if (c === "online") return "on";
  if (c === "offline") return "off";
  return "idle";
}

export function LiveGrid({ sessions }: { sessions: Session[] }) {
  const flagged = [...sessions].sort((a, b) => {
    const score = (s: Session) =>
      (String(s.attention) === "flagged" ? 2 : 0) + (String(s.lifecycle) === "BLOCKED" ? 2 : 0) + (String(s.connectivity) !== "online" ? 1 : 0);
    return score(b) - score(a);
  });
  if (flagged.length === 0) return <p className="muted">No sessions yet. Enroll candidates and open the exam.</p>;
  return (
    <>
      <h2>Live grid · {flagged.length} session(s)</h2>
      <div className="livegrid">
        {flagged.map((s) => (
          <Link className="livecell" key={s.session_id} to={`/sessions/${s.session_id}`}>
            <div className="name">{String(s.display_name || s.session_id)}</div>
            <div>
              <span className={`badge b-${String(s.lifecycle).toLowerCase()}`}>{String(s.lifecycle)}</span>{" "}
              {String(s.attention) === "flagged" && <span className="badge b-bad">flagged</span>}
            </div>
            <div className="row">
              <span className={`dot ${connClass(s)}`} />
              {String(s.connectivity)}
              {s.heartbeat_age_ms !== undefined && s.heartbeat_age_ms !== null && ` · ${s.heartbeat_age_ms}ms ago`}
            </div>
            <div className="row">
              {String(s.thumbnail_available) === "true" ? "📷 thumbnail available" : "no thumbnail"}
              {s.claim_owner ? ` · claimed` : ""}
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
