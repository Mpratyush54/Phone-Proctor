import type { Server } from "node:http";
import { flushPersist } from "./db/persist.js";
import { createLogger } from "./log.js";

/** Drain on SIGTERM/SIGINT: stop accepting, flush the durable write chain, then exit. */
export function armGracefulShutdown(server: Server, service: string) {
  const log = createLogger(service, process.env.LOG_LEVEL || "info");
  let stopping = false;
  const stop = async (signal: string) => {
    if (stopping) return;
    stopping = true;
    log.info({ signal }, `${service} draining`);
    try {
      await flushPersist();
    } catch (err) {
      log.warn({ err }, "persist flush failed during drain");
    }
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 5000).unref?.();
  };
  process.on("SIGTERM", () => void stop("SIGTERM"));
  process.on("SIGINT", () => void stop("SIGINT"));
}
