// Chaos matrix: slow/hanging peer (ROADMAP Phase 5). A peer that accepts a
// sync stream and never responds must not block the caller forever —
// pullFromPeer's explicit AbortSignal.timeout is what CLAUDE.md's
// "explicit timeouts everywhere" rule is actually for. This exercises the
// real sync-protocol.js code against a real hung responder, not a mock.
import { createLibp2p } from "libp2p";
import { tcp } from "@libp2p/tcp";
import { noise } from "@chainsafe/libp2p-noise";
import { yamux } from "@chainsafe/libp2p-yamux";
import { identify } from "@libp2p/identify";

import { SYNC_PROTOCOL, pullFromPeer } from "./sync-protocol.js";
import { Logger } from "./logger.js";

const TIMEOUT_MS = 1000;
const HANG_MS = 15000; // far longer than TIMEOUT_MS — the responder never replies in time

async function makeNode(port) {
  return createLibp2p({
    addresses: { listen: [`/ip4/127.0.0.1/tcp/${port}`] },
    transports: [tcp()],
    connectionEncrypters: [noise()],
    streamMuxers: [yamux()],
    services: { identify: identify() },
  });
}

function fakeLedgerClient() {
  return {
    async getVector() {
      return {};
    },
    async postEvents() {
      throw new Error("should never be called — the pull is expected to time out first");
    },
  };
}

async function main() {
  const slowPeer = await makeNode(9990);
  const requester = await makeNode(9991);

  // The hung responder: accepts the stream, never sends anything back.
  slowPeer.handle(SYNC_PROTOCOL, async () => {
    await new Promise((resolve) => setTimeout(resolve, HANG_MS));
  });

  await requester.dial(slowPeer.getMultiaddrs()[0]);
  await new Promise((r) => setTimeout(r, 300)); // let the connection settle

  const logger = new Logger("chaos-test", `${process.cwd()}/chaos-slow-peer.log`);
  const start = Date.now();
  const merged = await pullFromPeer(
    requester, fakeLedgerClient(), slowPeer.peerId, TIMEOUT_MS, logger,
  );
  const elapsed = Date.now() - start;

  // Deliberately not calling .stop() on either node: the responder's
  // handler is still asleep for HANG_MS and libp2p.stop() waits for open
  // protocol handlers to finish, which would block this script for the
  // full hang duration — exactly the kind of thing this test exists to
  // prove doesn't happen to pullFromPeer's *caller*. The process exits
  // right after printing the result, so leaked handles here are harmless.
  console.log(`pullFromPeer returned after ${elapsed}ms (timeout was ${TIMEOUT_MS}ms)`);
  console.log(`merged count: ${merged}`);

  const failures = [];
  if (merged !== 0) {
    failures.push(`expected merged=0 from a timed-out pull, got ${merged}`);
  }
  // Generous upper bound: must return close to the timeout, not hang for
  // anywhere near HANG_MS (proves the timeout fired, not that the peer
  // eventually responded).
  if (elapsed > TIMEOUT_MS + 4000) {
    failures.push(`took ${elapsed}ms — timeout did not fire, caller was blocked`);
  }

  if (failures.length > 0) {
    console.error("FAILED:");
    for (const f of failures) {
      console.error(`  - ${f}`);
    }
    process.exit(1);
  }
  console.log("PASSED: slow peer did not block the caller past its timeout");
  process.exit(0);
}

main().catch((err) => {
  console.error("chaos-slow-peer-test crashed:", err);
  process.exit(1);
});
