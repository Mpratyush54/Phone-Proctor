import { z } from "zod";

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
  OIDC_ISSUER: z.string().default("http://127.0.0.1:5556"),
  OIDC_CLIENT_ID: z.string().default("phone-proctor"),
  OIDC_CLIENT_SECRET: z.string().default("dev-secret"),
  OIDC_REDIRECT_URL: z.string().default("http://127.0.0.1:8080/api/v1/auth/callback"),
  SESSION_SECRET: z.string().default("dev-session-secret-change-me"),
  TOKEN_PEPPER: z.string().default("dev-pepper"),
  ORIGIN_ALLOWLIST: z.string().default("http://127.0.0.1:8080,http://localhost:5173"),
  LIVEKIT_URL: z.string().optional(),
  LIVEKIT_API_KEY: z.string().optional(),
  LIVEKIT_API_SECRET: z.string().optional(),
});

export type AppConfig = z.infer<typeof schema> & { origins: string[]; production: boolean };

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const parsed = schema.safeParse(env);
  if (!parsed.success) {
    throw new Error(`invalid config: ${parsed.error.message}`);
  }
  const cfg = parsed.data;
  const production = cfg.NODE_ENV === "production";
  if (production) {
    const required = ["DATABASE_URL", "SESSION_SECRET", "TOKEN_PEPPER", "OIDC_ISSUER", "OIDC_CLIENT_SECRET"] as const;
    for (const key of required) {
      if (!env[key]) {
        throw new Error(`refusing to start: missing production config ${key}`);
      }
    }
    if (cfg.SESSION_SECRET === "dev-session-secret-change-me" || cfg.TOKEN_PEPPER === "dev-pepper") {
      throw new Error("refusing to start: default secrets are not allowed in production");
    }
  }
  return {
    ...cfg,
    production,
    origins: cfg.ORIGIN_ALLOWLIST.split(",").map((s) => s.trim()).filter(Boolean),
  };
}
