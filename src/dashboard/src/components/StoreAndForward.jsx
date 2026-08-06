import { useMemo, useState } from "react";

// Store-and-forward visibility.
//
// Aether does not require a continuous network path between every node.
// The ledger is a G-Set CRDT, so merge is commutative/associative/
// idempotent — two nodes reconcile correctly whenever they happen to meet,
// in any order, however long the gap. That makes a device that walks
// between disconnected clusters a transport in its own right: it carries
// everything it holds and hands it over on the next contact.
//
// This panel makes that concrete: how much of the ledger originated here
// vs. arrived from elsewhere and is being retained for onward delivery,
// and whether there is currently anybody in range to hand it to.
//
// Deliberately NOT shown: which peer relayed a given report, or when it
// arrived. The D5 envelope carries origin identity (node_id, seq) and
// causal order (lamport) only — there is no route or receive-time field,
// and inventing one here would be fabricating provenance the system never
// recorded. See the "known" vs "not tracked" note rendered below.
const PEER_LIVE_WINDOW_S = 90;

export function StoreAndForward({ events, peers, health }) {
  const [expanded, setExpanded] = useState(false);

  const stats = useMemo(() => {
    const selfId = health?.node_id ?? null;
    const byOrigin = new Map();
    for (const envelope of events ?? []) {
      byOrigin.set(envelope.node_id, (byOrigin.get(envelope.node_id) ?? 0) + 1);
    }
    const authoredHere = selfId ? (byOrigin.get(selfId) ?? 0) : 0;
    const total = (events ?? []).length;
    const carried = total - authoredHere;
    const foreignOrigins = [...byOrigin.entries()]
      .filter(([originId]) => originId !== selfId)
      .sort((a, b) => b[1] - a[1]);
    return { selfId, total, authoredHere, carried, foreignOrigins };
  }, [events, health]);

  const livePeers = (peers ?? []).filter(
    (p) => p.seconds_since_heartbeat <= PEER_LIVE_WINDOW_S,
  ).length;

  let posture;
  let postureClass;
  if (stats.carried > 0 && livePeers === 0) {
    posture = `Carrying ${stats.carried} report${stats.carried === 1 ? "" : "s"} from ` +
      `${stats.foreignOrigins.length} other node${stats.foreignOrigins.length === 1 ? "" : "s"} ` +
      `with no peer in range — will forward on next contact.`;
    postureClass = "posture carrying";
  } else if (livePeers > 0) {
    posture = `Syncing with ${livePeers} peer${livePeers === 1 ? "" : "s"} in range.`;
    postureClass = "posture syncing";
  } else if (stats.total > 0) {
    posture = "All reports originated here. No peer in range to forward to yet.";
    postureClass = "posture isolated";
  } else {
    posture = "No reports held yet.";
    postureClass = "posture idle";
  }

  return (
    <section className="panel">
      <h2>
        Store &amp; Forward
        <button
          type="button"
          className="info-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "hide" : "what is this?"}
        </button>
      </h2>

      <div className={postureClass}>{posture}</div>

      <dl className="sf-stats">
        <div>
          <dt>Authored here</dt>
          <dd>{stats.authoredHere}</dd>
        </div>
        <div>
          <dt>Carried for others</dt>
          <dd>{stats.carried}</dd>
        </div>
        <div>
          <dt>Peers in range</dt>
          <dd>{livePeers}</dd>
        </div>
      </dl>

      {stats.foreignOrigins.length > 0 && (
        <ul className="origin-list">
          {stats.foreignOrigins.map(([originId, count]) => (
            <li key={originId}>
              <span className="origin-id">{originId}</span>
              <span className="origin-count">
                {count} report{count === 1 ? "" : "s"} held
              </span>
            </li>
          ))}
        </ul>
      )}

      {expanded && (
        <div className="sf-explainer">
          <p>
            Nodes do not need a continuous connection to each other. The ledger is a
            grow-only CRDT, so any two nodes reconcile correctly whenever they next
            meet — in any order, after any gap. A device that moves between
            disconnected groups carries everything it holds and hands it over on
            contact, so reports spread even with no end-to-end network path.
          </p>
          <p className="sf-caveat">
            <strong>Known:</strong> which node originally authored each report, and its
            causal order (Lamport clock).{" "}
            <strong>Not tracked:</strong> the route a report travelled, which peer
            relayed it, or when it arrived here — the event envelope records origin and
            ordering only, so this panel does not claim a delivery path it never saw.
          </p>
        </div>
      )}
    </section>
  );
}
