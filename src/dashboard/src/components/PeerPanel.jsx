// Peer liveness, as reported by the transport's heartbeats to the D4
// service. seconds_since_heartbeat is derived from time.monotonic() on the
// Python side — elapsed-time display only, never ordering (CLAUDE.md).
const STALE_AFTER_S = 90;

export function PeerPanel({ peers, health, stale }) {
  return (
    <section className="panel">
      <h2>
        Mesh Status
        <span className={stale ? "badge badge-down" : "badge badge-up"}>
          {stale ? "LEDGER UNREACHABLE" : "CONNECTED"}
        </span>
      </h2>
      {health && (
        <div className="node-self">
          this node: <strong>{health.node_id}</strong> · {health.event_count} events
        </div>
      )}
      {(!peers || peers.length === 0) && <div className="empty">No peers heard from yet.</div>}
      <ul className="peer-list">
        {(peers ?? []).map((peer) => {
          const silent = peer.seconds_since_heartbeat > STALE_AFTER_S;
          return (
            <li key={peer.peer_id} className={silent ? "peer peer-silent" : "peer"}>
              <span className="peer-dot" aria-hidden="true" />
              <span className="peer-id">{peer.peer_id}</span>
              <span className="peer-age">{Math.round(peer.seconds_since_heartbeat)}s ago</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
