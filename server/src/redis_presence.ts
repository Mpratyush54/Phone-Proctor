import { createServer } from "node:http";
import type { Duplex } from "node:stream";

/** Redis is optional until Track G. Not a source of truth. */
export class Presence {
  constructor(private down = false) {}
  setDown(v: boolean) { this.down = v; }
  async heartbeat(sessionId: string, store: { presence: Map<string, { online: boolean; ts: number }> }) {
    store.presence.set(sessionId, { online: true, ts: Date.now() });
    if (this.down) return { degraded: true, source: "postgres" };
    return { degraded: false, source: "redis" };
  }
}

export function originGuard(allow: string[], req: { headers: Record<string, string | string[] | undefined> }, socket: Duplex) {
  const origin = String(req.headers.origin || "");
  if (origin && !allow.includes(origin)) {
    socket.destroy();
    return false;
  }
  return true;
}

void createServer;
