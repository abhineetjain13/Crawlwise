import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = process.cwd();
const SEARCH_ROOTS = ["app", "components"];
const TOKEN_ESCAPE_PATTERN = /\b(?:bg|text|border|shadow)-\[var\(--/;

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    const stats = statSync(path);
    if (stats.isDirectory()) return walk(path);
    if (!/\.(tsx|ts)$/.test(path)) return [];
    if (/\.(test|spec)\.(tsx|ts)$/.test(path)) return [];
    return [path];
  });
}

const violations = [];

for (const root of SEARCH_ROOTS) {
  const rootPath = join(ROOT, root);
  if (!existsSync(rootPath)) continue;
  for (const file of walk(rootPath)) {
    const normalized = relative(ROOT, file).replaceAll("\\", "/");
    const text = readFileSync(file, "utf8");
    if (!TOKEN_ESCAPE_PATTERN.test(text)) continue;
    violations.push(normalized);
  }
}
}

if (violations.length) {
  console.error("Raw CSS-var Tailwind token escapes found:");
  for (const file of violations) {
    console.error(`- ${file}`);
  }
  process.exit(1);
}
