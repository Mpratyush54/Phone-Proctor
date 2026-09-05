import { loadConfig } from "./config.js";
import { createApp } from "./app.js";
import { globalStore } from "./store.js";
import { hydrate } from "./db/hydrate.js";
import { createLogger } from "./log.js";
import { armGracefulShutdown } from "./shutdown.js";

async function main() {
  const cfg = loadConfig();
  const log = createLogger("api", cfg.LOG_LEVEL);
  globalStore.loadSnapshot(await hydrate());
  if (cfg.seedDemo) {
    globalStore.seedDev();
    log.warn("SEED_DEMO=true: demo org/user provisioned (dev only, never production)");
  }
  const app = createApp(cfg, globalStore);
  const server = app.listen(cfg.API_PORT, cfg.API_HOST, () => {
    log.info({ host: cfg.API_HOST, port: cfg.API_PORT }, "api listening");
  });
  armGracefulShutdown(server, "api");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
