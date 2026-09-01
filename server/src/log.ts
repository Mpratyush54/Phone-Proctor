import pino from "pino";

const REDACT = ["req.headers.cookie", "req.headers.authorization", "password", "token", "secret", "email", "refresh_token"];

export function createLogger(service: string, level = process.env.LOG_LEVEL || "info") {
  return pino({
    level,
    base: { service },
    redact: { paths: REDACT, censor: "[redacted]" },
    timestamp: pino.stdTimeFunctions.isoTime,
  });
}

export function requestId(): string {
  return crypto.randomUUID();
}
