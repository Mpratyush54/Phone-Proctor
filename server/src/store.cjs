/**
 * In-memory session/event store. Swap for Mongo later without changing callers.
 */
class SessionStore {
  constructor() {
    this.mode = process.env.PP_MONGO_URL ? "mongo-pending" : "memory";
    this.exams = new Map();
    this.sessions = new Map();
    this.events = new Map(); // sessionId -> array
  }

  createExam({ title, code }) {
    const exam = {
      id: code,
      code,
      title,
      created_at: Date.now(),
    };
    this.exams.set(code, exam);
    return exam;
  }

  listExams() {
    return Array.from(this.exams.values());
  }

  upsertSession( partial ) {
    const prev = this.sessions.get(partial.id) || {};
    const session = {
      ...prev,
      ...partial,
      updated_at: Date.now(),
      created_at: prev.created_at || Date.now(),
    };
    this.sessions.set(partial.id, session);
    return session;
  }

  getSession(id) {
    return this.sessions.get(id) || null;
  }

  touchSession(id, patch = {}) {
    if (!id) return;
    const prev = this.sessions.get(id) || { id };
    this.sessions.set(id, { ...prev, ...patch, updated_at: Date.now() });
  }

  appendEvent(sessionId, event) {
    if (!sessionId) return;
    if (!this.events.has(sessionId)) this.events.set(sessionId, []);
    const row = { ...event, ts: Date.now() };
    this.events.get(sessionId).push(row);
    // Cap memory
    const arr = this.events.get(sessionId);
    if (arr.length > 5000) arr.splice(0, arr.length - 5000);
    return row;
  }

  listEvents(sessionId, limit = 200) {
    const arr = this.events.get(sessionId) || [];
    return arr.slice(-limit);
  }

  sessionCount() {
    return this.sessions.size;
  }
}

module.exports = { SessionStore };
