// SPDX-License-Identifier: MIT
// The site's scripts are ES modules named .js with no package.json beside
// them, which Node would read as CommonJS. Import them from their text.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const ROOT = fileURLToPath(new URL("../../", import.meta.url));

export async function loadSite(name) {
  const source = readFileSync(new URL(`../../site/${name}`, import.meta.url));
  return import(`data:text/javascript;base64,${source.toString("base64")}`);
}
