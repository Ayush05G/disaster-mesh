// D4 API client. The transport is a stateless relay (D2) — this is its
// only window into ledger state; it never touches the JSONL directly.
// Every call carries an explicit timeout (CLAUDE.md: "explicit timeouts
// everywhere").
export class LedgerClient {
  constructor(baseUrl, timeoutMs) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.timeoutMs = timeoutMs;
  }

  async _fetch(path, options = {}) {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!resp.ok) {
      throw new Error(`${options.method ?? "GET"} ${path} -> HTTP ${resp.status}`);
    }
    return resp;
  }

  async getVector() {
    const resp = await this._fetch("/vector");
    return resp.json();
  }

  async getEventsSince(vector) {
    const qs = new URLSearchParams({ since: JSON.stringify(vector) });
    const resp = await this._fetch(`/events?${qs}`);
    return resp.json();
  }

  async postEvents(envelopes) {
    if (envelopes.length === 0) {
      return { merged: 0, total: 0 };
    }
    const resp = await this._fetch("/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(envelopes),
    });
    return resp.json();
  }

  async heartbeat(peerId, address) {
    await this._fetch("/peers/heartbeat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ peer_id: peerId, address }),
    });
  }

  async health() {
    const resp = await this._fetch("/health");
    return resp.json();
  }
}
