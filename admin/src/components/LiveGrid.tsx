import { Link } from "react-router-dom";
import React from "react";
import type { Snapshot } from "../stream";

const CELL = 96;
const OVERSCAN = 4;

/** Windowed grid so 1,000 candidates do not mount 1,000 DOM nodes. */
export function LiveGrid({ sessions }: { sessions: Snapshot["sessions"] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(800);
  const [scroll, setScroll] = React.useState(0);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth || 800));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const cols = Math.max(1, Math.floor(width / 180));
  const rows = Math.ceil(sessions.length / cols) || 1;
  const startRow = Math.max(0, Math.floor(scroll / CELL) - OVERSCAN);
  const visibleRows = Math.ceil(480 / CELL) + OVERSCAN * 2;
  const endRow = Math.min(rows, startRow + visibleRows);
  const start = startRow * cols;
  const end = Math.min(sessions.length, endRow * cols);
  const slice = sessions.slice(start, end);
  return (
    <>
      <h2>Live grid</h2>
      <p>{sessions.length} sessions (virtualized)</p>
      <div
        ref={ref}
        className="grid-window"
        style={{ height: 480, overflow: "auto", position: "relative" }}
        onScroll={(e) => setScroll((e.target as HTMLDivElement).scrollTop)}
      >
        <div style={{ height: rows * CELL, position: "relative" }}>
          <div className="grid" style={{ position: "absolute", top: startRow * CELL, left: 0, right: 0 }}>
            {slice.map((s) => (
              <Link className="cell" key={s.session_id} to={`/sessions/${s.session_id}`}>
                <div>{String(s.display_name || s.session_id)}</div>
                <div>{String(s.lifecycle)} / {String(s.connectivity)}</div>
                <div>thumb: {String(s.thumbnail_available)}</div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
