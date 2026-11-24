import { loadConfig } from "./config.js";
import { createApp } from "./app.js";
import { globalStore } from "./store.js";
import { createLogger } from "./log.js";

export function startApi(store = globalStore) {
  const cfg = loadConfig();
  const log = createLogger("api", cfg.LOG_LEVEL);
  const app = createApp(cfg, store);
  return app.listen(cfg.API_PORT, cfg.API_HOST, () => {
    log.info({ host: cfg.API_HOST, port: cfg.API_PORT }, "api listening");
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  startApi();
}
