# Backlog

Deferred ideas. Anything that surfaces mid-phase but falls outside that phase's scope lands
here instead of derailing the work. Each phase appends its own deferred items on close.

Format: `- [ ] <idea> — surfaced in Phase N, <one-line why it was deferred>`

## Candidates (pre-Phase 0)

- [ ] BLE transport alongside ad-hoc Wi-Fi — broader device reach, but a second transport
      doubles the Phase 3 surface area. Revisit once Wi-Fi mesh converges reliably.
- [ ] Image / vision input to the SLM — the schema already anticipates it; text-first keeps
      Phase 2 honest and the quantized vision models fit the Pi budget poorly.
- [ ] Severity-based routing priority (HIGH hazards preempt gossip queue) — needs a working
      baseline gossip layer to measure against.
- [ ] Cryptographically signed hazard reports — matters for a real deployment where a
      malicious node could inject false hazards. Out of scope until the mesh works.
- [ ] Node battery / resource awareness in routing decisions.
- [ ] Ledger compaction — JSONL grows unbounded over a long deployment.
- [ ] True AP-less ad-hoc Wi-Fi mesh — V1 assumes a shared LAN segment (hotspot/router),
      per ROADMAP scope decision 1. A project of its own on Windows/consumer hardware;
      libp2p is layer-2-agnostic, so nothing above changes when it lands.
- [ ] Mutable hazard status ("resolved" / updates) — reintroduces the LWW merge machinery
      the G-Set decision deliberately removed. Only add with a real field need.
- [ ] Mobile-phone nodes — the overview promises them; needs a mobile runtime story
      (Termux? React Native + native libp2p?) that doesn't exist in the V1 stack.
- [ ] CI runner (GitHub Actions) — repo currently has no remote; tests run locally by rule.
- [ ] Local PMTiles basemap for the dashboard — surfaced in Phase 4; deferred because the
      region extract is a sized download needing an explicit OK (same class as the
      phi3:mini pull). The inline graticule style works today; when a region is chosen,
      add the `pmtiles` protocol adapter + vector layers, and extend the offline audit
      allowlist only if the style JSON carries identifier URLs.

## Phase 0

_(none yet)_
