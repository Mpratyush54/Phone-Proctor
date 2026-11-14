import type { PoolClient } from "pg";

export async function withTransaction<T>(
  client: PoolClient,
  fn: (client: PoolClient) => Promise<T>,
): Promise<T> {
  await client.query("BEGIN");
  try {
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch {
      // ignore rollback failure; the original error is more useful
    }
    throw err;
  }
}
