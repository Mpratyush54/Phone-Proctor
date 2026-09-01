import http from "node:http";
import { WebSocketServer, type WebSocket } from "ws";
import { loadConfig } from "./config.js";
import { createLogger } from "./log.js";
import { globalStore, type Store } from "./store.js";
import { rejectUnknownMajor } from "./contracts.js";

const RATE = new Map<WebSocket, { n: number; t: number }>();

export function startGateway(store: Store = globalStore, opts?: { listen?: boolean; port?: number; host?: string }) {
  const cfg = loadConfig();
  const log = createLogger("gateway", cfg.LOG_LEVEL);
  const maxConn = cfg.GATEWAY_MAX_CONNECTIONS;
  const pollMs = cfg.COMMAND_POLL_MS;
  const agentSockets = new Map<string, WebSocket>();
  const deliveredBySocket = new WeakMap<WebSocket, Set<string>>();
  const consoles: { examId: string; ws: WebSocket; seq: number }[] = [];

  const server = http.createServer((req, res) => {
    if (req.url === "/health/live") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ status: "live", service: "gateway", agents: agentSockets.size }));
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

  function pump() {
    for (const [sid, ws] of agentSockets) {
      if (ws.readyState !== 1) continue;
      const seen = deliveredBySocket.get(ws) || new Set<string>();
      deliveredBySocket.set(ws, seen);
      for (const cmd of store.pendingCommands(sid)) {
        if (seen.has(cmd.id)) continue;
        seen.add(cmd.id);
        store.markDispatched(cmd.id);
        ws.send(
          JSON.stringify({
            v: 1,
            type: "command",
            payload: {
              command_id: cmd.id,
              type: cmd.type,
              idempotency_key: cmd.idempotencyKey,
              session_id: sid,
            },
          }),
        );
      }
    }
    for (const c of consoles) {
      if (c.ws.readyState !== 1) continue;
      for (const item of store.deltas(c.examId, c.seq)) {
        c.ws.send(JSON.stringify({ v: 1, type: "console-delta", payload: item }));
        c.seq = item.stream_seq;
      }
    }
  }
  const timer = setInterval(pump, pollMs);
  timer.unref?.();

  wss.on("connection", (ws, req) => {
    const origin = req.headers.origin;
    if (origin && !cfg.origins.includes(origin) && cfg.production) {
      ws.close(4403, "origin");
      return;
    }
    const url = new URL(req.url || "/", "http://127.0.0.1");
    if (url.pathname === "/console") {
      const examId = url.searchParams.get("exam_id") || "";
      const after = Number(url.searchParams.get("after_seq") || 0);
      const slot = { examId, ws, seq: after };
      consoles.push(slot);
      for (const item of store.deltas(examId, after)) {
        ws.send(JSON.stringify({ v: 1, type: "console-delta", payload: item }));
        slot.seq = item.stream_seq;
      }
      ws.on("close", () => {
        const i = consoles.indexOf(slot);
        if (i >= 0) consoles.splice(i, 1);
      });
      return;
    }
    if (agentSockets.size >= maxConn) {
      // allow takeover of an existing session after resume; cap new sockets until then
    }
    let sessionId = "";
    let hello = false;
    ws.on("message", async (data) => {
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
        if (!agentSockets.has(sessionId) && agentSockets.size >= maxConn) {
          ws.close(4429, "capacity");
          return;
        }
        const prev = agentSockets.get(sessionId);
        if (prev && prev !== ws) {
          prev.close(4409, "takeover");
        }
        agentSockets.set(sessionId, ws);
        const session = store.sessions.get(sessionId);
        if (session) {
          session.connGen += 1;
          session.connectivity = "online";
          session.observed = session.observed === "NEW" ? "READY" : session.observed;
        }
        ws.send(
          JSON.stringify({
            v: 1,
            type: "resumed",
            payload: { session_id: sessionId, connection_generation: session?.connGen, pending_commands: store.pendingCommands(sessionId).length },
          }),
        );
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
          await store.awaitDurable();
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
    ws.on("close", () => {
      RATE.delete(ws);
      if (sessionId && agentSockets.get(sessionId) === ws) agentSockets.delete(sessionId);
    });
  });
  if (opts?.listen === false) {
    server.on("close", () => clearInterval(timer));
    return server;
  }
  const port = opts?.port ?? cfg.GATEWAY_PORT;
  const host = opts?.host ?? cfg.GATEWAY_HOST;
  server.listen(port, host, () => {
    log.info({ host, port, maxConn }, "gateway listening");
  });
  server.on("close", () => clearInterval(timer));
  return server;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  startGateway();
}
