// Aether P2P mesh transport (ROADMAP D1). Stateless relay — all ledger
// state lives in the Python ledger service (D2); this process only talks
// to it over the D4 REST API. Peer discovery is mDNS (production path,
// D1) plus an optional static bootstrap list, which makes the
// multi-node-on-one-machine harness deterministic without depending on
// this host's multicast/firewall behavior (see ROADMAP risk register).
import { createLibp2p } from "libp2p";
import { tcp } from "@libp2p/tcp";
import { mdns } from "@libp2p/mdns";
import { gossipsub } from "@chainsafe/libp2p-gossipsub";
import { noise } from "@chainsafe/libp2p-noise";
import { yamux } from "@chainsafe/libp2p-yamux";
import { identify } from "@libp2p/identify";
import { multiaddr } from "@multiformats/multiaddr";

import { Logger } from "./logger.js";
import { LedgerClient } from "./ledger-client.js";
import { registerSyncHandler, pullFromPeer } from "./sync-protocol.js";

const HAZARDS_TOPIC = "aether/hazards/v1";

function envInt(name, fallback) {
  const raw = process.env[name];
  return raw ? parseInt(raw, 10) : fallback;
}

async function main() {
  const nodeId = process.env.AETHER_NODE_ID ?? "node_local";
  const ledgerUrl = process.env.AETHER_LEDGER_URL ?? "http://127.0.0.1:8700";
  const p2pPort = envInt("AETHER_P2P_PORT", 9000);
  const timeoutMs = envInt("AETHER_TIMEOUT_MS", 5000);
  const antiEntropyIntervalMs = envInt("AETHER_ANTI_ENTROPY_INTERVAL_MS", 30000);
  const localPollIntervalMs = envInt("AETHER_LOCAL_POLL_INTERVAL_MS", 2000);
  const dataDir = process.env.AETHER_DATA_DIR ?? `data/${nodeId}`;
  const bootstrapPeers = (process.env.AETHER_BOOTSTRAP_PEERS ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const logger = new Logger(nodeId, `${dataDir}/network.log`);
  const ledgerClient = new LedgerClient(ledgerUrl, timeoutMs);

  // Fail fast and clearly if the ledger service isn't reachable — same
  // startup UX as the Python ingestion worker.
  try {
    await ledgerClient.health();
  } catch (err) {
    logger.error(`ledger service unreachable at ${ledgerUrl}: ${err.message}`);
    process.exit(1);
  }

  const libp2p = await createLibp2p({
    addresses: { listen: [`/ip4/0.0.0.0/tcp/${p2pPort}`] },
    transports: [tcp()],
    connectionEncrypters: [noise()],
    streamMuxers: [yamux()],
    peerDiscovery: [mdns({ interval: 5000 })],
    services: {
      identify: identify(),
      pubsub: gossipsub({ emitSelf: false }),
    },
  });

  registerSyncHandler(libp2p, ledgerClient, logger, timeoutMs);

  let lastKnownLocalSeq = 0;

  // --- gossipsub: receive live events from peers, merge into our ledger ---
  libp2p.services.pubsub.subscribe(HAZARDS_TOPIC);
  libp2p.services.pubsub.addEventListener("message", async (evt) => {
    if (evt.detail.topic !== HAZARDS_TOPIC) {
      return;
    }
    try {
      const envelope = JSON.parse(new TextDecoder().decode(evt.detail.data));
      const result = await ledgerClient.postEvents([envelope]);
      if (result.merged > 0) {
        logger.info(`gossip: merged event ${envelope.event_id}`);
      }
    } catch (err) {
      logger.warn(`gossip message handling failed: ${err.message}`);
    }
  });

  // --- anti-entropy on peer connect (D6) ---
  libp2p.addEventListener("peer:connect", async (evt) => {
    const peerId = evt.detail;
    logger.info(`peer connected: ${peerId.toString()}`);
    const merged = await pullFromPeer(libp2p, ledgerClient, peerId, timeoutMs, logger);
    if (merged > 0) {
      logger.info(`anti-entropy (on connect) merged ${merged} events from ${peerId.toString()}`);
    }
  });

  // --- periodic anti-entropy sweep across all connected peers (D6: 30s) ---
  const antiEntropyTimer = setInterval(async () => {
    for (const connection of libp2p.getConnections()) {
      const merged = await pullFromPeer(
        libp2p, ledgerClient, connection.remotePeer, timeoutMs, logger,
      );
      if (merged > 0) {
        logger.info(
          `anti-entropy (sweep) merged ${merged} events from ${connection.remotePeer.toString()}`,
        );
      }
    }
  }, antiEntropyIntervalMs);

  // --- local change detection: gossip out newly ingested local events ---
  const localPollTimer = setInterval(async () => {
    try {
      const vector = await ledgerClient.getVector();
      const currentSeq = vector[nodeId] ?? 0;
      if (currentSeq > lastKnownLocalSeq) {
        const newEvents = await ledgerClient.getEventsSince({ [nodeId]: lastKnownLocalSeq });
        for (const envelope of newEvents) {
          // Gossip is a best-effort fast path — anti-entropy (D6) is the
          // guaranteed delivery mechanism once a peer connects. Publishing
          // with zero subscribers throws (NoPeersSubscribedToTopic, e.g.
          // right at startup before any peer has joined); that must not
          // stop us from advancing lastKnownLocalSeq below, or we'd retry
          // publishing the same already-durable event forever.
          try {
            const data = new TextEncoder().encode(JSON.stringify(envelope));
            await libp2p.services.pubsub.publish(HAZARDS_TOPIC, data);
            logger.info(`gossiped local event ${envelope.event_id}`);
          } catch (err) {
            logger.warn(`gossip publish skipped for ${envelope.event_id}: ${err.message}`);
          }
        }
        lastKnownLocalSeq = currentSeq;
      }
    } catch (err) {
      logger.warn(`local change poll failed: ${err.message}`);
    }
  }, localPollIntervalMs);

  // --- bootstrap peers: deterministic dialing, supplements mDNS ---
  for (const addr of bootstrapPeers) {
    try {
      await libp2p.dial(multiaddr(addr), { signal: AbortSignal.timeout(timeoutMs) });
      logger.info(`dialed bootstrap peer ${addr}`);
    } catch (err) {
      logger.warn(`failed to dial bootstrap peer ${addr}: ${err.message}`);
    }
  }

  logger.info(`peer started: ${nodeId} listening on tcp/${p2pPort}, ledger=${ledgerUrl}`);
  for (const addr of libp2p.getMultiaddrs()) {
    logger.info(`listening on ${addr.toString()}`);
  }

  const shutdown = async () => {
    logger.info("shutting down...");
    clearInterval(antiEntropyTimer);
    clearInterval(localPollTimer);
    await libp2p.stop();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((err) => {
  console.error("fatal error starting peer:", err);
  process.exit(1);
});
