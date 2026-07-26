import { useMemo } from "react";

// Feed order is Lamport clock (then event_id as a stable tiebreak) — never
// the payload timestamp, which is display metadata from unsynced clocks
// (CLAUDE.md Critical Rule 2). Newest causal events first.
const FEED_LIMIT = 100;

export function EventFeed({ hazards }) {
  const ordered = useMemo(() => {
    return [...hazards]
      .sort((a, b) => b.lamport - a.lamport || (a.event_id < b.event_id ? 1 : -1))
      .slice(0, FEED_LIMIT);
  }, [hazards]);

  return (
    <section className="panel panel-feed">
      <h2>
        Event Feed
        <span className="badge badge-count">{hazards.length}</span>
      </h2>
      {ordered.length === 0 && <div className="empty">No hazards in the ledger.</div>}
      <ul className="feed-list">
        {ordered.map((envelope) => (
          <li key={envelope.event_id} className="feed-item">
            <span className={`sev sev-${envelope.payload.severity}`}>
              {envelope.payload.severity}
            </span>
            <span className="feed-type">{envelope.payload.hazard_type}</span>
            <span className="feed-meta">
              {envelope.event_id} · L{envelope.lamport}
            </span>
          </li>
        ))}
      </ul>
      {hazards.length > FEED_LIMIT && (
        <div className="feed-truncated">showing latest {FEED_LIMIT}</div>
      )}
    </section>
  );
}
