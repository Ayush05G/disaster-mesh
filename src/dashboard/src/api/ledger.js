// D4 ledger service client. All URLs are relative ("/api/...") — the Vite
// dev/preview proxy forwards them to localhost:8700, so the shipped bundle
// contains no absolute origin and the CSP (connect-src 'self') holds.
// Every call carries an explicit timeout (CLAUDE.md: timeouts everywhere).

const TIMEOUT_MS = 5000;

async function get(path) {
  const resp = await fetch(`/api${path}`, {
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!resp.ok) {
    throw new Error(`GET ${path} -> HTTP ${resp.status}`);
  }
  return resp.json();
}

export function fetchHealth() {
  return get("/health");
}

export function fetchAllEvents() {
  return get("/events");
}

export function fetchPeers() {
  return get("/peers");
}
