// SPDX-License-Identifier: MIT
// For the Python tests: runs site/flash.js on a request file and prints JSON.
import { readFileSync } from "node:fs";
import { loadSite } from "./load.mjs";

const flash = await loadSite("flash.js");
const request = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const attempt = (run) => { try { return run(); } catch (error) { return null; } };
const out = { plans: {} };
for (const [name, options] of Object.entries(request.plans || {})) {
  try { out.plans[name] = flash.flashPlan(options); } catch (error) { out.plans[name] = { error: error.message }; }
}
out.quoted = (request.quote || []).map((text) => attempt(() => flash.shellQuote(text)));
out.homePaths = (request.quote || []).map((text) => attempt(() => flash.homePath(text)));
out.constants = { APP_PATH: flash.APP_PATH, APP_NAME: flash.APP_NAME, SERVER_PATH: flash.SERVER_PATH, AGENT_PORT: flash.AGENT_PORT,
  CONTROL_PORT: flash.CONTROL_PORT, AGENT_BANNER: flash.AGENT_BANNER, REPOSITORY: flash.REPOSITORY };
process.stdout.write(JSON.stringify(out));
