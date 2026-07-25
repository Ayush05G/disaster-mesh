// Offline build audit (ROADMAP Phase 4): Critical Rule 1 as a test, not a
// promise. Scans every file in dist/ for external-URL patterns that could
// cause a runtime network request. Any hit fails the build (exit 1).
//
// Wired into `npm run build` after `vite build` — a bundled dependency that
// quietly phones home (CDN font, telemetry endpoint, remote tile server)
// breaks CI here instead of breaking a disaster deployment in the field.
//
// Allowlisted: XML namespace URIs, schema/license identifiers, and other
// well-known non-fetched strings that legitimately appear in bundles.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import process from "node:process";

const DIST = new URL("../dist", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

const URL_PATTERN = /https?:\/\/[^\s"'`)<>\\]+/g;

// Substrings that mark a URL as a non-fetched identifier, not a request
// target. Kept deliberately narrow: when in doubt, fail the build and make
// a human look at it.
const ALLOWLIST = [
  "www.w3.org",             // SVG/XML namespace URIs
  "schemas.openxmlformats", // office XML namespaces
  "registry.npmjs.org",     // package provenance strings
  "github.com",             // repo/license pointers in banners
  "opensource.org",         // license URLs in comment banners
  "maplibre.org",           // attribution/license pointers in the maplibre banner
  "mapbox.com",             // spec/attribution pointers inherited by maplibre
  "openstreetmap.org",      // attribution pointer strings
  "mozilla.org",            // MDN links in comment banners
  "react.dev/errors",       // React embeds this in thrown error *messages* ("visit
                            // react.dev/errors/N for the full message") — printed
                            // to humans in stack traces, never fetched
  "example.com",            // placeholder hosts in bundled code paths
  "localhost",              // same-machine only, never external
  "127.0.0.1",              // same-machine only, never external
];

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, files);
    } else {
      files.push(full);
    }
  }
  return files;
}

function main() {
  let files;
  try {
    files = walk(DIST);
  } catch {
    console.error(`audit-offline: dist/ not found at ${DIST} — run vite build first`);
    return 1;
  }

  const violations = [];
  for (const file of files) {
    const text = readFileSync(file, "utf-8");
    for (const match of text.matchAll(URL_PATTERN)) {
      const url = match[0];
      if (ALLOWLIST.some((allowed) => url.includes(allowed))) {
        continue;
      }
      violations.push({ file: relative(DIST, file), url });
    }
  }

  if (violations.length > 0) {
    console.error("audit-offline: FAILED — external URLs found in dist/:");
    for (const v of violations) {
      console.error(`  ${v.file}: ${v.url}`);
    }
    console.error(
      "\nCritical Rule 1: nothing in the shipped bundle may fetch from the network.\n" +
      "Either remove the dependency/asset, vendor it locally, or — only if it is\n" +
      "provably a non-fetched identifier string — extend the allowlist with a comment.",
    );
    return 1;
  }

  console.log(`audit-offline: OK — ${files.length} files scanned, no external URLs`);
  return 0;
}

process.exit(main());
