import { loadConfig } from "./config.js";
import { createApp } from "./app.js";
import { globalStore } from "./store.js";
import { hydrate } from "./db/hydrate.js";
import { createLogger } from "./log.js";
import { armGracefulShutdown } from "./shutdown.js";
import { mountIdentityProvider, parseSeedUsers, seedUsers } from "./idp.js";

async function main() {
  const cfg = loadConfig();
  const log = createLogger("api", cfg.LOG_LEVEL);
  globalStore.loadSnapshot(await hydrate());
  if (cfg.seedDemo) {
    const { orgId } = globalStore.seedDev();
    log.warn("SEED_DEMO=true: demo org/user provisioned (dev only, never production)");
    const seeds = parseSeedUsers(process.env.SEED_USERS);
    if (seeds.length > 0) {
      await seedUsers(globalStore, orgId, seeds, cfg.OIDC_ISSUER.replace(/\/+$/, ""));
      log.warn(`SEED_USERS: provisioned ${seeds.length} login user(s) (dev only, never production)`);
    }
  }
  const app = createApp(cfg, globalStore);
  if (cfg.embeddedIdp) {
    mountIdentityProvider(app, cfg, globalStore);
    log.warn(`EMBEDDED_IDP: development identity provider mounted at ${cfg.OIDC_ISSUER} (dev only, never production)`);
  }
  const server = app.listen(cfg.API_PORT, cfg.API_HOST, () => {
    log.info({ host: cfg.API_HOST, port: cfg.API_PORT }, "api listening");
  });
  armGracefulShutdown(server, "api");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
