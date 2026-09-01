import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const here = path.dirname(fileURLToPath(import.meta.url));
export const MIGRATIONS_DIR = path.resolve(here, "../../migrations");

/** Split SQL into statements, respecting `--` comments, quotes, and $tag$ dollar quotes. */
export function splitSqlStatements(sql: string): string[] {
  const statements: string[] = [];
  let buf = "";
  let i = 0;
  let dollarTag: string | null = null;
  let inSingle = false;
  let inDouble = false;
  let inLineComment = false;
  let inBlockComment = false;

  const push = () => {
    const s = buf.trim();
    if (s) statements.push(s);
    buf = "";
  };

  while (i < sql.length) {
    const c = sql[i];
    const next = sql[i + 1];

    if (inLineComment) {
      buf += c;
      if (c === "\n") inLineComment = false;
      i += 1;
      continue;
    }
    if (inBlockComment) {
      buf += c;
      if (c === "*" && next === "/") {
        buf += "/";
        i += 2;
        inBlockComment = false;
        continue;
      }
      i += 1;
      continue;
    }
    if (dollarTag) {
      if (sql.startsWith(dollarTag, i)) {
        buf += dollarTag;
        i += dollarTag.length;
        dollarTag = null;
        continue;
      }
      buf += c;
      i += 1;
      continue;
    }
    if (inSingle) {
      buf += c;
      if (c === "'" && next === "'") {
        buf += "'";
        i += 2;
        continue;
      }
      if (c === "'") inSingle = false;
      i += 1;
      continue;
    }
    if (inDouble) {
      buf += c;
      if (c === '"') inDouble = false;
      i += 1;
      continue;
    }
    if (c === "-" && next === "-") {
      inLineComment = true;
      buf += c;
      i += 1;
      continue;
    }
    if (c === "/" && next === "*") {
      inBlockComment = true;
      buf += c;
      i += 1;
      continue;
    }
    if (c === "'") {
      inSingle = true;
      buf += c;
      i += 1;
      continue;
    }
    if (c === '"') {
      inDouble = true;
      buf += c;
      i += 1;
      continue;
    }
    if (c === "$") {
      const m = sql.slice(i).match(/^\$[A-Za-z0-9_]*\$/);
      if (m) {
        dollarTag = m[0];
        buf += dollarTag;
        i += dollarTag.length;
        continue;
      }
    }
    if (c === ";") {
      push();
      i += 1;
      continue;
    }
    buf += c;
    i += 1;
  }
  push();
  return statements;
}

export async function listMigrationFiles(dir = MIGRATIONS_DIR): Promise<string[]> {
  const names = (await readdir(dir)).filter((f) => f.endsWith(".sql")).sort();
  return names.map((n) => path.join(dir, n));
}

/** Apply `*.sql` files in lexical order. No-op when `databaseUrl` is unset. */
export async function runMigrations(databaseUrl?: string): Promise<void> {
  if (!databaseUrl) return;
  const files = await listMigrationFiles();
  const client = new pg.Client({ connectionString: databaseUrl, connectionTimeoutMillis: 5000 });
  await client.connect();
  try {
    for (const file of files) {
      const sql = await readFile(file, "utf8");
      const statements = splitSqlStatements(sql);
      for (const stmt of statements) {
        await client.query(stmt);
      }
    }
  } finally {
    await client.end();
  }
}

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    console.log("DATABASE_URL unset; skipping migrate");
    return;
  }
  await runMigrations(url);
  console.log("migrate complete");
}

const invoked = process.argv[1] ? path.basename(path.resolve(process.argv[1])).startsWith("migrate") : false;
if (invoked) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
