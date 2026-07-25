import { useMemo, useState } from "react";
import { fetchAllEvents, fetchHealth, fetchPeers } from "./api/ledger.js";
import { usePolling } from "./api/usePolling.js";
import { HazardMap } from "./components/HazardMap.jsx";
import { PeerPanel } from "./components/PeerPanel.jsx";
import { EventFeed } from "./components/EventFeed.jsx";
import { SeverityFilter } from "./components/SeverityFilter.jsx";

const EVENTS_POLL_MS = 2000;
const PEERS_POLL_MS = 5000;

export default function App() {
  const { data: events, stale } = usePolling(fetchAllEvents, EVENTS_POLL_MS);
  const { data: peers } = usePolling(fetchPeers, PEERS_POLL_MS);
  const { data: health } = usePolling(fetchHealth, PEERS_POLL_MS);

  const [activeSeverities, setActiveSeverities] = useState(
    () => new Set(["LOW", "MEDIUM", "HIGH"]),
  );

  const toggleSeverity = (level) => {
    setActiveSeverities((prev) => {
      const next = new Set(prev);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  };

  const hazards = useMemo(() => {
    if (!events) {
      return [];
    }
    return events.filter((e) => activeSeverities.has(e.payload.severity));
  }, [events, activeSeverities]);

  return (
    <div className="app">
      <header className="topbar">
        <h1>AETHER · mesh dashboard</h1>
        <SeverityFilter active={activeSeverities} onToggle={toggleSeverity} />
      </header>
      <main className="layout">
        <HazardMap hazards={hazards} />
        <aside className="sidebar">
          <PeerPanel peers={peers} health={health} stale={stale} />
          <EventFeed hazards={hazards} />
        </aside>
      </main>
    </div>
  );
}
