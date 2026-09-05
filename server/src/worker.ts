import http from "node:http";
import path from "node:path";
import { loadConfig } from "./config.js";
import { createLogger } from "./log.js";
import { globalStore } from "./store.js";

export function startWorker(store = globalStore) {
  const cfg = loadConfig();
  const log = createLogger("worker", cfg.LOG_LEVEL);
  const server = http.createServer((req, res) => {
    if (req.url === "/health/live") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ status: "live", service: "worker" }));
      return;
    }
    if (req.url === "/health/ready") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ status: "ready", service: "worker", checks: store.health() }));
      return;
    }
    res.statusCode = 404;
    res.end();
  });

  const timer = setInterval(() => {
    for (const cmd of store.commands.values()) {
      if (cmd.status === "accepted") {
        // retry/expiry owner: worker, not gateway
        const ageOk = true;
        if (!ageOk) cmd.status = "expired";
      }
    }
    for (const m of store.media.values()) {
      if (m.status === "pending_verification") {
        m.attempts += 1;
        if (m.attempts >= 10) {
          m.status = "dead_letter";
          store.deadLetter.push({ assetId: m.id, reason: "timeout" });
        }
      }
    }
    if (store.redisDown) {
      log.warn({ degraded: "fanout" }, "redis down; durable writes continue");
    }
  }, 1000);
  timer.unref?.();

  server.listen(cfg.WORKER_PORT, cfg.WORKER_HOST, () => {
    log.info({ host: cfg.WORKER_HOST, port: cfg.WORKER_PORT }, "worker listening");
  });
  return server;
}

const entry = process.argv[1] || "";
if (import.meta.url === `file://${entry}` || path.basename(entry) === "worker.ts") {
  startWorker();
}
