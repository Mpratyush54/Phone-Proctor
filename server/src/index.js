/**
 * Phone-Proctor central server (scaffold).
 *
 * - REST: health, exams (memory store by default)
 * - WS /agent  : laptop agent uplink (register, heartbeat, batches, ack)
 * - WS /exam/:sessionId : examiner live relay room
 *
 * Mongo / Redis are OPTIONAL. Without them the server runs in-memory so
 * local demos need zero external services.
 */
const http = require("http");
const path = require("path");
const express = require("express");
const cors = require("cors");
const { WebSocketServer } = require("ws");
const { v4: uuidv4 } = require("uuid");
const { SessionStore } = require("./store");
const { RoomHub } = require("./rooms");

const PORT = Number(process.env.PP_PORT || 8080);
const store = new SessionStore();
const rooms = new RoomHub();

const app = express();
app.use(cors());
app.use(express.json({ limit: "2mb" }));

// Static examiner UI placeholder
app.use("/admin", express.static(path.join(__dirname, "..", "admin", "public")));

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    mode: store.mode,
    sessions: store.sessionCount(),
    ts: Date.now(),
  });
});

app.post("/api/exams", (req, res) => {
  const exam = store.createExam({
    title: req.body?.title || "Untitled Exam",
    code: req.body?.code || uuidv4().slice(0, 8).toUpperCase(),
  });
  res.status(201).json(exam);
});

app.get("/api/exams", (_req, res) => {
  res.json(store.listExams());
});

app.get("/api/sessions/:id", (req, res) => {
  const s = store.getSession(req.params.id);
  if (!s) return res.status(404).json({ error: "not_found" });
  res.json(s);
});

app.get("/api/sessions/:id/events", (req, res) => {
  res.json(store.listEvents(req.params.id, Number(req.query.limit || 200)));
});

const server = http.createServer(app);
const wss = new WebSocketServer({ noServer: true });

server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  wss.handleUpgrade(req, socket, head, (ws) => {
    wss.emit("connection", ws, req, url);
  });
});

wss.on("connection", (ws, _req, url) => {
  if (url.pathname === "/agent") {
    attachAgent(ws);
    return;
  }
  const examMatch = url.pathname.match(/^\/exam\/([^/]+)$/);
  if (examMatch) {
    rooms.join(examMatch[1], ws, "examiner");
    ws.send(JSON.stringify({ op: "joined", session_id: examMatch[1], role: "examiner" }));
    return;
  }
  ws.close(1008, "unknown path");
});

function attachAgent(ws) {
  let sessionId = null;

  ws.on("message", async (raw) => {
    let msg;
    try {
      msg = JSON.parse(String(raw));
    } catch {
      return;
    }
    const op = msg.op;
    if (op === "register") {
      sessionId = msg.session_id || uuidv4().slice(0, 8);
      const session = store.upsertSession({
        id: sessionId,
        exam_code: msg.exam_code || "",
        student_id: msg.student_id || "",
        fingerprint: msg.fingerprint || "",
        integrity: msg.integrity || {},
        status: "live",
      });
      if (msg.integrity && msg.integrity.status === "TAMPERED") {
        store.appendEvent(sessionId, {
          type: "TAMPERED",
          data: msg.integrity,
        });
        rooms.broadcast(sessionId, {
          op: "flag",
          type: "TAMPERED",
          session_id: sessionId,
          data: msg.integrity,
        });
      }
      ws.send(JSON.stringify({ op: "registered", session }));
      rooms.broadcast(sessionId, { op: "presence", session_id: sessionId, status: "live" });
      return;
    }

    if (!sessionId) {
      sessionId = msg.session_id || null;
    }

    if (op === "heartbeat") {
      store.touchSession(sessionId || msg.session_id, msg);
      rooms.broadcast(sessionId || msg.session_id, {
        op: "heartbeat",
        session_id: sessionId || msg.session_id,
        counter: msg.counter,
        uptime_s: msg.uptime_s,
      });
      return;
    }

    if (op === "batch" && msg.batch) {
      const batch = msg.batch;
      const sid = batch.session_id || sessionId;
      store.appendEvent(sid, {
        type: batch.payload?.type || "EVENT",
        data: batch.payload?.data || {},
        seq_no: batch.seq_no,
        batch_id: batch.batch_id,
      });
      rooms.broadcast(sid, {
        op: "event",
        session_id: sid,
        batch,
      });
      // Ack so agent can compact WAL
      ws.send(JSON.stringify({ op: "ack", batch_ids: [batch.batch_id] }));
      return;
    }
  });

  ws.on("close", () => {
    if (sessionId) {
      store.touchSession(sessionId, { status: "disconnected" });
      rooms.broadcast(sessionId, {
        op: "presence",
        session_id: sessionId,
        status: "disconnected",
      });
    }
  });
}

server.listen(PORT, () => {
  console.log(`[PP-SERVER] listening on http://0.0.0.0:${PORT}`);
  console.log(`[PP-SERVER] agent WS   ws://<host>:${PORT}/agent`);
  console.log(`[PP-SERVER] exam room  ws://<host>:${PORT}/exam/<sessionId>`);
  console.log(`[PP-SERVER] admin UI   http://<host>:${PORT}/admin/`);
  console.log(`[PP-SERVER] store mode ${store.mode}`);
});
