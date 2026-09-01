import pg from "pg";

let cached: pg.Pool | null = null;

/** Create a Pool from DATABASE_URL. Returns null (no-op) when the URL is unset. */
export function createPool(databaseUrl?: string): pg.Pool | null {
  if (!databaseUrl) return null;
  return new pg.Pool({
    connectionString: databaseUrl,
    max: 10,
    connectionTimeoutMillis: 3000,
    idleTimeoutMillis: 10_000,
  });
}

/** Process-wide pool from `process.env.DATABASE_URL`, or null when unset. */
export function getPool(): pg.Pool | null {
  if (cached) return cached;
  cached = createPool(process.env.DATABASE_URL);
  return cached;
}

export async function closePool(): Promise<void> {
  if (!cached) return;
  const p = cached;
  cached = null;
  await p.end();
}
