import { randomBytes, scrypt as scryptCb, timingSafeEqual } from "node:crypto";
import express, { type Express, type Request, type Response } from "express";
import Provider from "oidc-provider";
import type { AppConfig } from "./config.js";
import { ApiError, type Store } from "./store.js";
import { enqueuePersist, upsertRoleAssignment, upsertUserAccount } from "./db/persist.js";

function scryptAsync(password: string, salt: Buffer, keylen: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    (scryptCb as (...args: unknown[]) => void)(
      password, salt, keylen, { N: 16384, r: 8, p: 1 },
      (err: unknown, dk: unknown) => (err ? reject(err) : resolve(dk as Buffer)),
    );
  });
}

/* ---------------- password hashing (scrypt) ---------------- */

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(16);
  const dk = await scryptAsync(password, salt, 64);
  return `scrypt$v1$16384$8$1$${salt.toString("base64")}$${dk.toString("base64")}`;
}

export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = stored.split("$");
  if (parts.length !== 7 || parts[0] !== "scrypt" || parts[1] !== "v1") return false;
  const [, , n, r, p, saltB64, hashB64] = parts;
  void n;
  void r;
  void p;
  const dk = await scryptAsync(password, Buffer.from(saltB64, "base64"), 64);
  const expected = Buffer.from(hashB64, "base64");
  if (dk.length !== expected.length) return false;
  return timingSafeEqual(dk, expected);
}

/* ---------------- env-seeded users: email:password:role,role;... ---------------- */

export interface SeedUser {
  email: string;
  password: string;
  roles: string[];
}

export function parseSeedUsers(raw: string | undefined): SeedUser[] {
  if (!raw) return [];
  return raw
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((entry) => {
      const [email, password, roles] = entry.split(":");
      if (!email || !password) throw new Error(`bad SEED_USERS entry: ${entry}`);
      return { email: email.trim(), password, roles: (roles || "").split(",").map((r) => r.trim()).filter(Boolean) };
    });
}

const VALID_ROLES = new Set(["invigilator", "lead_invigilator", "exam_admin", "reviewer", "platform_ops"]);

/** Provision env-defined users into the demo org (dev only; called explicitly at boot).
 * Users are linked to the embedded issuer so the OIDC callback resolves them. */
export async function seedUsers(store: Store, orgId: string, seeds: SeedUser[], issuer: string) {
  for (const s of seeds) {
    for (const role of s.roles) {
      if (!VALID_ROLES.has(role)) throw new Error(`bad role in SEED_USERS: ${role}`);
    }
    const existing = [...store.users.values()].find((u) => u.email === s.email.toLowerCase());
    const user = existing ?? store.upsertUser(s.email, issuer, `pending:${s.email.toLowerCase()}`, s.email.split("@")[0]);
    user.email = s.email.toLowerCase();
    user.issuer = issuer;
    user.subject = user.id;
    user.passwordHash = await hashPassword(s.password);
    if (process.env.DATABASE_URL) {
      enqueuePersist(() => upsertUserAccount({ ...user }));
    }
    if (!store.memberships.has(`${orgId}:${user.id}`)) {
      store.addMembership(orgId, user.id);
    }
    for (const role of s.roles) {
      if (!store.roles.some((r) => r.orgId === orgId && r.userId === user.id && r.role === role)) {
        const entry = { orgId, userId: user.id, role: role as (typeof store.roles)[number]["role"] };
        store.roles.push(entry);
        if (process.env.DATABASE_URL) {
          enqueuePersist(() => upsertRoleAssignment(entry));
        }
      }
    }
  }
}

/* ---------------- embedded OIDC provider ---------------- */

const loginAttempts = new Map<string, { fails: number; until: number }>();

function throttleKey(email: string, ip: string): string {
  return `${email.toLowerCase()}|${ip}`;
}

function loginPage(uid: string, error: string, email = ""): string {
  const safe = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Sign in — Phone-Proctor</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}
.card{background:#1e293b;border:1px solid #334155;border-radius:16px;padding:32px;width:100%;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
h1{margin:0 0 4px;font-size:22px}p.sub{margin:0 0 20px;color:#94a3b8;font-size:14px}
label{display:block;font-size:13px;color:#94a3b8;margin:12px 0 4px}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #475569;background:#0f172a;color:#fff;font-size:15px}
button{width:100%;margin-top:20px;padding:12px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-size:16px;font-weight:600;cursor:pointer}
button:hover{background:#1d4ed8}.err{background:#7f1d1d;border:1px solid #ef4444;border-radius:10px;padding:10px;margin-top:16px;font-size:13px}
</style></head><body><div class="card">
<h1>Sign in</h1><p class="sub">Phone-Proctor staff console</p>
<form method="post" action="login">
<label for="email">Email</label>
<input id="email" name="email" type="email" autocomplete="username" required value="${safe(email)}"/>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required/>
<button type="submit">Sign in</button>
</form>${error ? `<div class="err">${safe(error)}</div>` : ""}
</div></body></html>`;
}

/**
 * Mount a first-party OIDC provider (email + password) for development.
 * Production uses an external issuer (Keycloak/Auth0) via the same standard protocol.
 */
export function mountIdentityProvider(app: Express, cfg: AppConfig, store: Store) {
  const issuer = cfg.OIDC_ISSUER.replace(/\/+$/, "");
  const provider = new Provider(issuer, {
    clients: [
      {
        client_id: cfg.OIDC_CLIENT_ID,
        client_secret: cfg.OIDC_CLIENT_SECRET,
        redirect_uris: [cfg.OIDC_REDIRECT_URL],
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
        scope: "openid email profile",
        token_endpoint_auth_method: "client_secret_post",
      },
    ],
    findAccount: async (_ctx: unknown, sub: string) => {
      const user = store.users.get(sub);
      if (!user) return undefined;
      return {
        accountId: sub,
        async claims(_use: unknown, _scope: unknown) {
          return { sub, email: user.email, email_verified: true, name: user.name };
        },
      };
    },
    cookies: { keys: [cfg.SESSION_SECRET], secure: cfg.production },
    scopes: ["openid", "email", "profile", "offline_access"],
    claims: {
      email: ["email", "email_verified"],
      profile: ["name"],
    },
    features: { devInteractions: { enabled: false }, deviceFlow: { enabled: false } },
    responseTypes: ["code"],
    grantTypes: ["authorization_code", "refresh_token"],
    ttl: { Session: 8 * 3600, Grant: 10 * 60, Interaction: 300 },
  });

  const form = express.urlencoded({ extended: false });

  // Custom interaction routes FIRST so they win over the provider mount below.
  // Registered under both /op/interaction and /interaction: the provider
  // builds interaction URLs issuer-relative and edge deployments may strip
  // the mount prefix, so accept either.
  const interactionPaths = ["/op/interaction/:uid", "/interaction/:uid"];
  app.get(interactionPaths, async (req: Request, res: Response) => {
    try {
      const details = (await provider.interactionDetails(req, res)) as {
        uid: string;
        prompt: { name: string };
        params: Record<string, string>;
      };
      if (details.prompt.name !== "login") {
        res.status(400).send("unsupported interaction");
        return;
      }
      res.setHeader("content-type", "text/html").send(loginPage(details.uid, ""));
    } catch {
      res.status(400).send("expired or invalid login request");
    }
  });

  app.post(["/op/interaction/:uid/login", "/interaction/:uid/login"], form, async (req: Request, res: Response) => {
    const uid = String(req.params.uid);
    const email = String(req.body.email || "");
    const password = String(req.body.password || "");
    const fail = (message: string, status = 401) => res.status(status).setHeader("content-type", "text/html").send(loginPage(uid, message, email));
    try {
      const details = (await provider.interactionDetails(req, res)) as {
        params: { client_id: string };
        prompt: { name: string };
      };
      if (details.prompt.name !== "login") {
        fail("unexpected interaction state", 400);
        return;
      }
      const ip = String(req.ip || req.socket.remoteAddress || "");
      const key = throttleKey(email, ip);
      const record = loginAttempts.get(key);
      if (record && record.until > Date.now()) {
        fail("too many attempts — try again in a minute", 429);
        return;
      }
      const user = [...store.users.values()].find((u) => u.email === email.toLowerCase());
      const hash = (user as unknown as { passwordHash?: string } | undefined)?.passwordHash;
      const ok = !!user && !!hash && (await verifyPassword(password, hash));
      if (!ok) {
        const fails = (record?.fails ?? 0) + 1;
        loginAttempts.set(key, { fails, until: fails >= 5 ? Date.now() + 60_000 : 0 });
        fail("invalid email or password");
        return;
      }
      loginAttempts.delete(key);
      // First-party client: grant requested scopes/claims without an extra consent screen.
      const grant = new provider.Grant({ accountId: user!.id, clientId: details.params.client_id });
      grant.addOIDCScope("openid email profile");
      grant.addOIDCClaims(["email", "name"]);
      const grantId = await grant.save();
      await provider.interactionFinished(
        req,
        res,
        { login: { accountId: user!.id }, consent: { grantId } },
        { mergeWithLastSubmission: true },
      );
    } catch (err) {
      if (!res.headersSent) fail(err instanceof ApiError ? err.message : "login failed", 400);
    }
  });

  app.use("/op", provider.callback());
  return provider;
}
