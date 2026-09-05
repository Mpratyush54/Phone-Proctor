import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import * as jose from "jose";
import { ApiError } from "./store.js";

export interface ObjectStoreConfig {
  endpoint: string;
  bucket: string;
  region: string;
  accessKey?: string;
  secretKey?: string;
}

export function objectStoreConfigured(cfg: ObjectStoreConfig): boolean {
  return !!(cfg.accessKey && cfg.secretKey);
}

function hashSha256Hex(data: string): string {
  return createHash("sha256").update(data).digest("hex");
}

/**
 * SigV4 presigned URL (PUT or GET), path-style — works with AWS S3 and MinIO.
 * Pure offline computation; no SDK needed.
 */
export function presignUrl(
  cfg: ObjectStoreConfig,
  method: "PUT" | "GET",
  key: string,
  opts: { contentType?: string; expiresS?: number; now?: Date } = {},
): string {
  if (!objectStoreConfigured(cfg)) throw new ApiError("MEDIA_UNCONFIGURED", "object store not configured", 503);
  const expiresS = Math.min(Math.max(opts.expiresS ?? 300, 1), 7 * 86400);
  const now = opts.now ?? new Date();
  const amzDate = now.toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  const dateStamp = amzDate.slice(0, 8);
  const endpoint = new URL(cfg.endpoint);
  const encodedKey = key.split("/").map(encodeURIComponent).join("/");
  const canonicalUri = `/${cfg.bucket}/${encodedKey}`;
  const credentialScope = `${dateStamp}/${cfg.region}/s3/aws4_request`;
  const query: Record<string, string> = {
    "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
    "X-Amz-Credential": `${cfg.accessKey}/${credentialScope}`,
    "X-Amz-Date": amzDate,
    "X-Amz-Expires": String(expiresS),
    "X-Amz-SignedHeaders": "host",
  };
  const canonicalQuery = Object.keys(query)
    .sort()
    .map((k) => `${k}=${encodeURIComponent(query[k])}`)
    .join("&");
  const canonicalRequest = [method, canonicalUri, canonicalQuery, `host:${endpoint.host}`, "", "host", "UNSIGNED-PAYLOAD"].join(
    "\n",
  );
  const stringToSign = ["AWS4-HMAC-SHA256", amzDate, credentialScope, hashSha256Hex(canonicalRequest)].join("\n");
  const kDate = createHmac("sha256", "AWS4" + cfg.secretKey!).update(dateStamp).digest();
  const kRegion = createHmac("sha256", kDate).update(cfg.region).digest();
  const kService = createHmac("sha256", kRegion).update("s3").digest();
  const kSigning = createHmac("sha256", kService).update("aws4_request").digest();
  const signature = createHmac("sha256", kSigning).update(stringToSign).digest("hex");
  return `${endpoint.protocol}//${endpoint.host}${canonicalUri}?${canonicalQuery}&X-Amz-Signature=${signature}`;
}

/* ---------------- short-lived thumbnail tokens ---------------- */

export function signThumbnail(secret: string, assetId: string, expiresAtMs: number): string {
  return createHmac("sha256", secret).update(`${assetId}:${expiresAtMs}`).digest("base64url");
}

export function verifyThumbnail(secret: string, assetId: string, expiresAtMs: number, sig: string): boolean {
  if (!sig || Date.now() > expiresAtMs) return false;
  const expected = Buffer.from(signThumbnail(secret, assetId, expiresAtMs));
  const actual = Buffer.from(sig);
  if (expected.length !== actual.length) return false;
  return timingSafeEqual(expected, actual);
}

/* ---------------- LiveKit access tokens (standard JWT grants) ---------------- */

export interface LiveKitConfig {
  url?: string;
  apiKey?: string;
  apiSecret?: string;
}

export async function mintLiveKitToken(
  cfg: LiveKitConfig,
  opts: { room: string; identity: string; canPublish: boolean; canSubscribe: boolean; ttlS?: number },
): Promise<string> {
  if (!cfg.apiKey || !cfg.apiSecret) throw new ApiError("LIVEKIT_UNCONFIGURED", "live view not configured", 503);
  const now = Math.floor(Date.now() / 1000);
  return new jose.SignJWT({
    sub: opts.identity,
    name: opts.identity,
    video: {
      roomJoin: true,
      room: opts.room,
      canPublish: opts.canPublish,
      canSubscribe: opts.canSubscribe,
    },
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer(cfg.apiKey)
    .setIssuedAt(now)
    .setExpirationTime(now + (opts.ttlS ?? 3600))
    .sign(new TextEncoder().encode(cfg.apiSecret));
}
