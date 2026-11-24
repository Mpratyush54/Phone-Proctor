import http from "node:http";
import { WebSocketServer, type WebSocket } from "ws";
import { loadConfig } from "./config.js";
import { createLogger } from "./log.js";
import { globalStore, type Store } from "./store.js";
import { rejectUnknownMajor } from "./contracts.js";

export function startGateway(store: Store = globalStore, opts?: { listen?: boolean; port?: number; host?: string }) {
  const cfg = loadConfig();
  const log = createLogger("gateway", cfg.LOG_LEVEL);
  const maxConn = cfg.GATEWAY_MAX_CONNECTIONS;
  const pollMs = cfg.COMMAND_POLL_MS;
  const agentSockets = new Map<string, WebSocket>();
  const deliveredBySocket = new WeakMap<WebSocket, Set<string>>();
  type ConsoleSlot = { examId: string; ws: WebSocket; seq: number; streamId?: string; rawSession: string };
  const consoles = new Set<ConsoleSlot>();

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

  function pumpConsole(slot: ConsoleSlot) {
    if (slot.ws.readyState !== 1 || slot.ws.bufferedAmount > 512 * 1024) return;
    const staff = store.lookupStaff(slot.rawSession);
    if (!staff) {
      slot.ws.close(4401, "staff session");
      return;
    }
    try {
      store.requireExam(staff, slot.examId, "session.read");
    } catch {
      slot.ws.close(4403, "exam access");
      return;
    }
    const updates = store.consoleUpdates(slot.examId, slot.seq, slot.streamId);
    if (updates.resnapshot) {
      slot.ws.close(4410, "resnapshot");
      return;
    }
    slot.streamId = updates.stream_id;
    for (const item of updates.items) {
      if (slot.ws.bufferedAmount > 512 * 1024) break;
      slot.ws.send(JSON.stringify({ v: 1, type: "console-delta", payload: item }));
      slot.seq = item.stream_seq;
    }
  }

  function pump() {
    const pending = store.pendingCommandsBySession();
    const now = Date.now();
    for (const [sid, ws] of agentSockets) {
      if (ws.readyState !== 1) continue;
      const presence = store.presence.get(sid);
      if (presence && now - presence.ts > 45_000) {
        ws.close(4408, "heartbeat expired");
        continue;
      }
      if (ws.bufferedAmount > 512 * 1024) continue;
      const seen = deliveredBySocket.get(ws);
      const delivered = new Set<string>();
      deliveredBySocket.set(ws, delivered);
      for (const cmd of pending.get(sid) ?? []) {
        if (seen?.has(cmd.id)) {
          delivered.add(cmd.id);
          continue;
        }
        if (ws.bufferedAmount > 512 * 1024) break;
        delivered.add(cmd.id);
        store.markDispatched(cmd.id);
        ws.send(
          JSON.stringify({
            v: 1,
            type: "command",
            session_id: sid,
            payload: {
              command_id: cmd.id,
              command_type: cmd.type,
              type: cmd.type,
              idempotency_key: cmd.idempotencyKey,
              session_id: sid,
              control_generation: cmd.controlGen,
              body: cmd.body,
            },
          }),
        );
      }
    }
    for (const slot of consoles) pumpConsole(slot);
  }
  const timer = setInterval(pump, pollMs);
  timer.unref?.();

  wss.on("connection", (ws, req) => {
    ws.on("error", () => ws.terminate());
    const origin = req.headers.origin;
    if (origin && !cfg.origins.includes(origin) && cfg.production) {
      ws.close(4403, "origin");
      return;
    }
    const url = new URL(req.url || "/", "http://127.0.0.1");
    if (url.pathname === "/console") {
      const examId = url.searchParams.get("exam_id") || "";
      const seq = Number(url.searchParams.get("after_seq") || 0);
      const rawSession = /(?:^|;\s*)pp_session=([a-f0-9]{64})(?:;|$)/.exec(req.headers.cookie || "")?.[1];
      if (!rawSession || !Number.isSafeInteger(seq) || seq < 0) {
        ws.close(4401, "staff session");
        return;
      }
      const slot = { examId, ws, seq, rawSession, streamId: url.searchParams.get("stream_id") ?? undefined };
      consoles.add(slot);
      ws.on("close", () => consoles.delete(slot));
      pumpConsole(slot);
      return;
    }
    let sessionId = "";
    let credentialId = "";
    let hello = false;
    const handshakeTimer = setTimeout(() => ws.close(4408, "handshake timeout"), 10_000);
    handshakeTimer.unref();
    const bucket = { n: 0, t: Date.now() };
    ws.on("message", async (data) => {
      if (Date.now() - bucket.t > 1000) {
        bucket.n = 0;
        bucket.t = Date.now();
      }
      bucket.n += 1;
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
        if (!hello || sessionId) {
          ws.close(4400, "order");
          return;
        }
        const payload = msg.payload as { session_id?: string; device_credential_id?: string; camera_ready?: boolean } | undefined;
        const device = store.devices.get(payload?.device_credential_id ?? "");
        const session = store.sessions.get(payload?.session_id ?? "");
        if (!device || device.revoked || device.kind !== "laptop" || !session || device.enrollmentId !== session.enrollmentId) {
          ws.close(4401, "credential");
          return;
        }
        if (!agentSockets.has(session.id) && agentSockets.size >= maxConn) {
          ws.close(4429, "capacity");
          return;
        }
        sessionId = session.id;
        credentialId = device.id;
        clearTimeout(handshakeTimer);
        const prev = agentSockets.get(sessionId);
        if (prev && prev !== ws) prev.close(4409, "takeover");
        agentSockets.set(sessionId, ws);
        session.connGen += 1;
        if (device.desktop) store.applyDesktopPrecheck(sessionId, payload?.camera_ready === true);
        store.updateConnectivity(sessionId, "online");
        ws.send(
          JSON.stringify({
            v: 1,
            type: "resumed",
            payload: { session_id: sessionId, connection_generation: session.connGen, pending_commands: store.pendingCommands(sessionId).length,
              observed_lifecycle_state: session.observed, desired_lifecycle_state: session.desired },
          }),
        );
        return;
      }
      if (agentSockets.get(sessionId) !== ws || store.devices.get(credentialId)?.revoked) {
        ws.close(4401, "session");
        return;
      }
      if (type === "heartbeat") {
        store.updateConnectivity(sessionId, "online");
        const cameraReady = (msg.payload as { camera_ready?: unknown } | undefined)?.camera_ready;
        if (store.devices.get(credentialId)?.desktop && typeof cameraReady === "boolean") {
          store.applyDesktopPrecheck(sessionId, cameraReady);
          ws.send(JSON.stringify({ v: 1, type: "heartbeat-ok",
            payload: { observed_lifecycle_state: store.sessions.get(sessionId)?.observed } }));
        } else {
          ws.send(JSON.stringify({ v: 1, type: "heartbeat-ok" }));
        }
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
          const durableCursor = await store.awaitDurableEvent(sessionId, Number(msg.seq_no));
          ws.send(JSON.stringify({ v: 1, type: "ack", payload: { acked_through: durableCursor ?? r.acked_through, session_id: sessionId } }));
        } catch (err) {
          const e = err as { code?: string };
          ws.send(JSON.stringify({ v: 1, type: "nack", payload: { seq_no: msg.seq_no, code: e.code || "UNAVAILABLE", terminal: e.code === "SCHEMA_REJECT" } }));
        }
        return;
      }
      if (type === "command-result") {
        const payload = msg.payload as { command_id?: string; ok?: boolean; observed_lifecycle_state?: string } | undefined;
        try {
          if (typeof payload?.command_id !== "string" || typeof payload.ok !== "boolean") throw new Error("invalid command result");
          store.commandResult(sessionId, payload.command_id, payload.ok, payload.observed_lifecycle_state);
        } catch {
          ws.send(JSON.stringify({ v: 1, type: "nack", payload: { seq_no: 0, code: "VALIDATION", terminal: false } }));
        }
      }
    });
    ws.on("close", () => {
      clearTimeout(handshakeTimer);
      if (sessionId && agentSockets.get(sessionId) === ws) {
        agentSockets.delete(sessionId);
        store.updateConnectivity(sessionId, "offline");
      }
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
