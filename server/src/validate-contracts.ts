import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadAjv, rejectUnknownMajor } from "./contracts.js";

const examplesDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../contracts/v1/examples");
const ajv = loadAjv();
let failed = 0;
for (const file of fs.readdirSync(examplesDir)) {
  if (!file.endsWith(".json")) continue;
  const name = file.split("__")[0];
  const data = JSON.parse(fs.readFileSync(path.join(examplesDir, file), "utf8"));
  if (data.v !== undefined) {
    try {
      rejectUnknownMajor(data);
    } catch {
      console.error("FAIL major", file);
      failed++;
      continue;
    }
  }
  const validate = ajv.getSchema(name);
  if (!validate) {
    console.error("missing schema", name);
    failed++;
    continue;
  }
  if (!validate(data)) {
    console.error("FAIL", file, validate.errors);
    failed++;
  } else {
    console.log("OK  ", file);
  }
}
if (failed) process.exit(1);
