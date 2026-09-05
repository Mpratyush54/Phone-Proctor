import { z } from "zod";

const DEV_SECRETS = new Set(["dev-secret", "dev-session-secret-change-me", "dev-pepper", ""]);

function isLoopbackUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.hostname === "127.0.0.1" || u.hostname === "localhost" || u.hostname === "::1";
  } catch {
    return false;
  }
}

function isHttpsUrl(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

const schema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  LOG_LEVEL: z.string().default("info"),
  API_HOST: z.string().default("127.0.0.1"),
  API_PORT: z.coerce.number().default(8080),
  GATEWAY_HOST: z.string().default("127.0.0.1"),
  GATEWAY_PORT: z.coerce.number().default(8081),
  WORKER_HOST: z.string().default("127.0.0.1"),
  WORKER_PORT: z.coerce.number().default(8082),
  DATABASE_URL: z.string().optional(),
  REDIS_URL: z.string().optional(),
  OBJECT_STORE_ENDPOINT: z.string().default("http://127.0.0.1:9000"),
  OBJECT_STORE_BUCKET: z.string().default("phone-proctor"),
  OBJECT_STORE_ACCESS_KEY: z.string().optional(),
  OBJECT_STORE_SECRET_KEY: z.string().optional(),
  OBJECT_STORE_REGION: z.string().default("us-east-1"),
  OIDC_ISSUER: z.string().default("http://127.0.0.1:5556"),
  OIDC_CLIENT_ID: z.string().default("phone-proctor"),
  OIDC_CLIENT_SECRET: z.string().default("dev-secret"),
  OIDC_REDIRECT_URL: z.string().default("http://127.0.0.1:8080/api/v1/auth/callback"),
  OIDC_ACR_VALUES: z.string().optional(),
  OIDC_MAX_AGE: z.coerce.number().optional(),
  BOOTSTRAP_ADMIN_EMAIL: z.string().optional(),
  SESSION_SECRET: z.string().default("dev-session-secret-change-me"),
  TOKEN_PEPPER: z.string().default("dev-pepper"),
  TOKEN_PEPPER_PREVIOUS: z.string().optional(),
  ORIGIN_ALLOWLIST: z.string().default("http://127.0.0.1:8080,http://localhost:5173"),
  LIVEKIT_URL: z.string().optional(),
  LIVEKIT_API_KEY: z.string().optional(),
  LIVEKIT_API_SECRET: z.string().optional(),
  ALLOW_DEV_LOGIN: z.string().optional(),
  SEED_DEMO: z.string().optional(),
  SEED_USERS: z.string().optional(),
  EMBEDDED_IDP: z.string().optional(),
  MEDIA_FAKE: z.string().optional(),
});

export type AppConfig = z.infer<typeof schema> & {
  origins: string[];
  production: boolean;
  allowDevLogin: boolean;
  seedDemo: boolean;
  embeddedIdp: boolean;
  mediaFake: boolean;
};

function fail(message: string): never {
  throw new Error(`refusing to start: ${message}`);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const parsed = schema.safeParse(env);
  if (!parsed.success) {
    throw new Error(`invalid config: ${parsed.error.message}`);
  }
  const cfg = parsed.data;
  const production = cfg.NODE_ENV === "production";
  if (production) {
    const required = [
      "DATABASE_URL",
      "SESSION_SECRET",
      "TOKEN_PEPPER",
      "OIDC_ISSUER",
      "OIDC_CLIENT_ID",
      "OIDC_CLIENT_SECRET",
      "OIDC_REDIRECT_URL",
      "ORIGIN_ALLOWLIST",
    ] as const;
    for (const key of required) {
      if (!env[key]) fail(`missing production config ${key}`);
    }
    if (DEV_SECRETS.has(cfg.SESSION_SECRET) || DEV_SECRETS.has(cfg.TOKEN_PEPPER) || DEV_SECRETS.has(cfg.OIDC_CLIENT_SECRET)) {
      fail("default secrets are not allowed in production");
    }
    if (!isHttpsUrl(cfg.OIDC_ISSUER)) fail("OIDC_ISSUER must be an https URL in production");
    if (!isHttpsUrl(cfg.OIDC_REDIRECT_URL)) fail("OIDC_REDIRECT_URL must be an https URL in production");
    const origins = cfg.ORIGIN_ALLOWLIST.split(",").map((s) => s.trim()).filter(Boolean);
    if (origins.length === 0) fail("ORIGIN_ALLOWLIST must list at least one origin in production");
    for (const origin of origins) {
      if (origin === "*" || origin.includes("*")) fail("ORIGIN_ALLOWLIST must not contain wildcards in production");
      if (!isHttpsUrl(origin)) fail(`ORIGIN_ALLOWLIST entry must be https in production: ${origin}`);
    }
    if (isLoopbackUrl(cfg.DATABASE_URL!)) fail("DATABASE_URL must not point at localhost in production");
  }
  const warnings: string[] = [];
  if (!cfg.REDIS_URL) warnings.push("REDIS_URL unset: presence/fanout run degraded");
  if (!cfg.OBJECT_STORE_ACCESS_KEY || !cfg.OBJECT_STORE_SECRET_KEY) {
    warnings.push("OBJECT_STORE keys unset: media uploads disabled (fail-closed 503)");
  }
  if (!cfg.LIVEKIT_URL || !cfg.LIVEKIT_API_KEY || !cfg.LIVEKIT_API_SECRET) {
    warnings.push("LIVEKIT_* unset: live view disabled (fail-closed 503)");
  }
  for (const w of warnings) console.warn(`[config] ${w}`);
  return {
    ...cfg,
    production,
    allowDevLogin: !production && env.ALLOW_DEV_LOGIN === "true",
    seedDemo: !production && env.SEED_DEMO === "true",
    embeddedIdp: !production && env.EMBEDDED_IDP === "true",
    mediaFake: !production && env.MEDIA_FAKE === "true",
    origins: cfg.ORIGIN_ALLOWLIST.split(",").map((s) => s.trim()).filter(Boolean),
  };
}
