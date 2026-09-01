import http from "node:http";
import { WebSocketServer, type WebSocket } from "ws";
import { loadConfig } from "./config.js";
import { createLogger } from "./log.js";
import { globalStore } from "./store.js";
import { rejectUnknownMajor } from "./contracts.js";

const RATE = new Map<WebSocket, { n: number; t: number }>();

export function startGateway(store = globalStore) {
  const cfg = loadConfig();
  const log = createLogger("gateway", cfg.LOG_LEVEL);
  if (cfg.production) {
    // WSS is terminated at the load balancer; this process speaks WS internally.
  }
  const server = http.createServer((req, res) => {
    if (req.url === "/health/live") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ status: "live", service: "gateway" }));
      return;
    }
    if (req.url === "/health/ready") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ status: "ready", service: "gateway", checks: store.health() }));
      return;
    }
    res.statusCode = 404;
    res.end();
  });
  const wss = new WebSocketServer({ server, maxPayload: 256 * 1024 });
  wss.on("connection", (ws, req) => {
    const origin = req.headers.origin;
    if (origin && !cfg.origins.includes(origin) && cfg.production) {
      ws.close(4403, "origin");
      return;
    }
    let sessionId = "";
    let hello = false;
    ws.on("message", (data) => {
      const bucket = RATE.get(ws) || { n: 0, t: Date.now() };
      if (Date.now() - bucket.t > 1000) {
        bucket.n = 0;
        bucket.t = Date.now();
      }
      bucket.n += 1;
      RATE.set(ws, bucket);
      if (bucket.n > 40) {
        ws.send(JSON.stringify({ v: 1, type: "nack", payload: { code: "RATE_LIMIT", terminal: false, seq_no: 1 } }));
        return;
      }
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(String(data));
        rejectUnknownMajor(msg);
      } catch {
        ws.send(JSON.stringify({ v: 1, type: "nack", payload: { seq_no: 0, code: "SCHEMA_REJECT", terminal: true } }));
        return;
      }
      const type = msg.type;
      if (type === "hello") {
        hello = true;
        ws.send(JSON.stringify({ v: 1, type: "hello-ok" }));
        return;
      }
      if (type === "resume") {
        if (!hello) {
          ws.close(4400, "order");
          return;
        }
        const payload = msg.payload as { session_id: string; device_credential_id: string };
        const device = store.devices.get(payload.device_credential_id);
        if (!device || device.revoked) {
          ws.close(4401, "credential");
          return;
        }
        sessionId = payload.session_id;
        const session = store.sessions.get(sessionId);
        if (session) {
          session.connGen += 1;
          session.connectivity = "online";
          session.observed = session.observed === "NEW" ? "READY" : session.observed;
        }
        ws.send(JSON.stringify({ v: 1, type: "resumed", payload: { session_id: sessionId } }));
        return;
      }
      if (type === "heartbeat") {
        if (sessionId) {
          const s = store.sessions.get(sessionId);
          if (s) s.connectivity = "online";
          store.presence.set(sessionId, { online: true, ts: Date.now() });
        }
        ws.send(JSON.stringify({ v: 1, type: "heartbeat-ok" }));
        return;
      }
      if (type === "event") {
        try {
          const r = store.ingestEvent(
            sessionId,
            Number(msg.seq_no),
            String(msg.batch_id),
            String(msg.payload_hash),
            msg.payload,
          );
          ws.send(JSON.stringify({ v: 1, type: "ack", payload: { acked_through: r.acked_through, session_id: sessionId } }));
        } catch (err) {
          const e = err as { code?: string };
          ws.send(JSON.stringify({ v: 1, type: "nack", payload: { seq_no: msg.seq_no, code: e.code || "VALIDATION", terminal: e.code === "SCHEMA_REJECT" } }));
        }
        return;
      }
      if (type === "command-result") {
        const payload = msg.payload as { command_id: string; ok: boolean; observed_lifecycle_state: string };
        store.commandResult(sessionId, payload.command_id, payload.ok, payload.observed_lifecycle_state);
      }
    });
  });
  server.listen(cfg.GATEWAY_PORT, cfg.GATEWAY_HOST, () => {
    log.info({ host: cfg.GATEWAY_HOST, port: cfg.GATEWAY_PORT }, "gateway listening");
  });
  return server;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  startGateway();
}
