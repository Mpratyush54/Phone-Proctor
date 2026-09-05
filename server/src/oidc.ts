import { createHash, randomBytes } from "node:crypto";
import * as jose from "jose";
import type { AppConfig } from "./config.js";
import { ApiError, type Store } from "./store.js";

export interface OidcDiscovery {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  jwks_uri: string;
}

const discoveryCache = new Map<string, { doc: OidcDiscovery; expires: number }>();

function fetchWithTimeout(url: string, init: RequestInit, ms = 10_000): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, { ...init, signal: ctrl.signal }).finally(() => clearTimeout(timer));
}

function normalizeIssuer(value: string): string {
  return value.replace(/\/+$/, "");
}

/** Fetch and validate the provider's discovery document (cached 10 minutes). */
export async function discoverIssuer(issuer: string): Promise<OidcDiscovery> {
  const now = Date.now();
  const cached = discoveryCache.get(issuer);
  if (cached && cached.expires > now) return cached.doc;
  const wellKnown = `${normalizeIssuer(issuer)}/.well-known/openid-configuration`;
  let res: Response;
  try {
    res = await fetchWithTimeout(wellKnown, { headers: { accept: "application/json" } });
  } catch (err) {
    throw new ApiError("AUTH_DENIED", `issuer unreachable: ${(err as Error).message}`, 502);
  }
  if (!res.ok) throw new ApiError("AUTH_DENIED", "issuer discovery failed", 502);
  const doc = (await res.json()) as Partial<OidcDiscovery>;
  if (!doc.issuer || !doc.authorization_endpoint || !doc.token_endpoint || !doc.jwks_uri) {
    throw new ApiError("AUTH_DENIED", "issuer discovery incomplete", 502);
  }
  if (normalizeIssuer(doc.issuer) !== normalizeIssuer(issuer)) {
    throw new ApiError("AUTH_DENIED", "issuer mismatch", 502);
  }
  const out: OidcDiscovery = {
    issuer: doc.issuer,
    authorization_endpoint: doc.authorization_endpoint,
    token_endpoint: doc.token_endpoint,
    jwks_uri: doc.jwks_uri,
  };
  discoveryCache.set(issuer, { doc: out, expires: now + 10 * 60_000 });
  return out;
}

export function base64urlSha256(input: string): string {
  return createHash("sha256").update(input).digest("base64url");
}

export interface BeginOptions {
  prompt?: string;
  acrValues?: string;
  maxAge?: number;
}

/** Start an OIDC round. Verifier stays server-side; only the opaque state goes in the cookie. */
export async function beginOidc(
  cfg: AppConfig,
  store: Store,
  opts: BeginOptions = {},
): Promise<{ state: string; url: string }> {
  const doc = await discoverIssuer(cfg.OIDC_ISSUER);
  const state = randomBytes(16).toString("hex");
  const nonce = randomBytes(16).toString("hex");
  const verifier = randomBytes(32).toString("base64url");
  store.startOidc(state, nonce, verifier);
  const params = new URLSearchParams({
    client_id: cfg.OIDC_CLIENT_ID,
    redirect_uri: cfg.OIDC_REDIRECT_URL,
    response_type: "code",
    scope: "openid email profile",
    state,
    nonce,
    code_challenge: base64urlSha256(verifier),
    code_challenge_method: "S256",
  });
  if (opts.prompt) params.set("prompt", opts.prompt);
  if (opts.acrValues) params.set("acr_values", opts.acrValues);
  if (opts.maxAge !== undefined) params.set("max_age", String(opts.maxAge));
  return { state, url: `${doc.authorization_endpoint}?${params.toString()}` };
}

export interface OidcClaims {
  issuer: string;
  sub: string;
  email?: string;
  name?: string;
  authTime?: number;
  acr?: string;
}

export interface CompleteOptions {
  requireFreshAuthSeconds?: number;
  requireAcr?: string;
}

/** Exchange the code, verify the id_token (JWKS, iss/aud/exp/nonce), consume the tx. */
export async function completeOidc(
  cfg: AppConfig,
  store: Store,
  state: string,
  code: string,
  opts: CompleteOptions = {},
): Promise<OidcClaims> {
  const tx = store.takeOidcTx(state);
  const doc = await discoverIssuer(cfg.OIDC_ISSUER);
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: cfg.OIDC_REDIRECT_URL,
    client_id: cfg.OIDC_CLIENT_ID,
    client_secret: cfg.OIDC_CLIENT_SECRET,
    code_verifier: tx.verifier,
  });
  let tokenRes: Response;
  try {
    tokenRes = await fetchWithTimeout(
      doc.token_endpoint,
      { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body },
    );
  } catch (err) {
    throw new ApiError("AUTH_DENIED", `token endpoint unreachable: ${(err as Error).message}`, 502);
  }
  if (!tokenRes.ok) {
    let detail = "";
    try {
      const errBody = (await tokenRes.json()) as { error?: string; error_description?: string };
      detail = errBody.error_description || errBody.error || "";
    } catch {
      detail = "";
    }
    throw new ApiError("AUTH_DENIED", `token exchange failed${detail ? `: ${detail}` : ""}`, 401);
  }
  const tokens = (await tokenRes.json()) as { id_token?: string; access_token?: string };
  if (!tokens.id_token) throw new ApiError("AUTH_DENIED", "missing id_token", 401);
  let payload: jose.JWTPayload;
  try {
    const jwks = jose.createRemoteJWKSet(new URL(doc.jwks_uri));
    const verified = await jose.jwtVerify(tokens.id_token, jwks, {
      issuer: doc.issuer,
      audience: cfg.OIDC_CLIENT_ID,
    });
    payload = verified.payload;
  } catch {
    throw new ApiError("AUTH_DENIED", "invalid id_token", 401);
  }
  if (payload.nonce !== tx.nonce) throw new ApiError("AUTH_DENIED", "nonce mismatch", 401);
  if (typeof payload.sub !== "string" || !payload.sub) throw new ApiError("AUTH_DENIED", "missing sub", 401);
  if (opts.requireFreshAuthSeconds !== undefined) {
    if (typeof payload.auth_time !== "number" || Date.now() / 1000 - payload.auth_time > opts.requireFreshAuthSeconds) {
      throw new ApiError("AUTH_DENIED", "stale authentication", 401);
    }
  }
  if (opts.requireAcr && payload.acr !== opts.requireAcr) {
    throw new ApiError("AUTH_DENIED", "acr not satisfied", 401);
  }
  return {
    issuer: payload.iss!,
    sub: payload.sub,
    email: typeof payload.email === "string" ? payload.email : undefined,
    name: typeof payload.name === "string" ? payload.name : undefined,
    authTime: typeof payload.auth_time === "number" ? payload.auth_time : undefined,
    acr: typeof payload.acr === "string" ? payload.acr : undefined,
  };
}
