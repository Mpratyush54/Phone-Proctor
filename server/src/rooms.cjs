/** Per-session WebSocket relay rooms (examiner viewers). */
class RoomHub {
  constructor() {
    this.rooms = new Map(); // sessionId -> Set<ws>
  }

  join(sessionId, ws, role = "examiner") {
    if (!this.rooms.has(sessionId)) this.rooms.set(sessionId, new Set());
    const set = this.rooms.get(sessionId);
    set.add(ws);
    ws._pp_session = sessionId;
    ws._pp_role = role;
    ws.on("close", () => {
      set.delete(ws);
      if (set.size === 0) this.rooms.delete(sessionId);
    });
  }

  broadcast(sessionId, msg) {
    if (!sessionId) return;
    const set = this.rooms.get(sessionId);
    if (!set) return;
    const raw = typeof msg === "string" ? msg : JSON.stringify(msg);
    for (const ws of set) {
      if (ws.readyState === 1) {
        try {
          ws.send(raw);
        } catch {
          /* ignore */
        }
      }
    }
  }
}

module.exports = { RoomHub };
