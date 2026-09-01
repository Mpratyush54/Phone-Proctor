import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const contractsRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../contracts/v1");

export function loadAjv() {
  const ajv = new Ajv({ allErrors: true, strict: false, allowUnionTypes: true });
  addFormats(ajv);
  const schemaDir = path.join(contractsRoot, "schemas");
  for (const file of fs.readdirSync(schemaDir)) {
    if (!file.endsWith(".schema.json")) continue;
    const schema = JSON.parse(fs.readFileSync(path.join(schemaDir, file), "utf8"));
    ajv.addSchema(schema, file.replace(".schema.json", ""));
  }
  return ajv;
}

export function rejectUnknownMajor(msg: { v?: unknown }) {
  if (msg.v !== 1) {
    const err = new Error("unknown major version");
    (err as Error & { code: string }).code = "SCHEMA_REJECT";
    throw err;
  }
}
