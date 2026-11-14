import assert from "node:assert/strict";
import test from "node:test";
import { createPool } from "../src/db/pool.js";
import { runMigrations } from "../src/db/migrate.js";
import { ping, postgresStatus } from "../src/db/persist.js";
import { Store } from "../src/store.js";

test("migrate applies SQL and SELECT 1", async (t) => {
  if (!process.env.DATABASE_URL) {
    t.skip("DATABASE_URL unset");
    return;
  }
  await runMigrations(process.env.DATABASE_URL);
  const pool = createPool(process.env.DATABASE_URL);
  assert.ok(pool, "createPool should return a Pool when DATABASE_URL is set");
  try {
    const r = await pool.query("SELECT 1 AS ok");
    assert.equal(Number(r.rows[0].ok), 1);
    const status = await ping();
    assert.equal(status, "ok");
    assert.equal(postgresStatus(), "ok");
    const store = new Store();
    assert.equal(store.health().postgres, "ok");
  } finally {
    await pool.end();
  }
});

test("health postgres is memory when DATABASE_URL unset", (t) => {
  if (process.env.DATABASE_URL) {
    t.skip("DATABASE_URL set");
    return;
  }
  assert.equal(postgresStatus(), "memory");
  const store = new Store();
  assert.equal(store.health().postgres, "memory");
});
