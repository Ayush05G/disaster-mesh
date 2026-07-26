import { useEffect, useRef, useState } from "react";

// Poll a fetcher on an interval. Failures mark the connection stale rather
// than crashing the UI — a dashboard on a mesh node must degrade, not die,
// when its local ledger service restarts (fail loud: the banner shows it).
export function usePolling(fetcher, intervalMs) {
  const [data, setData] = useState(null);
  const [stale, setStale] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const result = await fetcherRef.current();
        if (!cancelled) {
          setData(result);
          setStale(false);
        }
      } catch {
        if (!cancelled) {
          setStale(true);
        }
      }
    }

    tick();
    const timer = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return { data, stale };
}
