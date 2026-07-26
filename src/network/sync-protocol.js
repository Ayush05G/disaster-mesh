// D6 anti-entropy: on peer connect and every 30s, exchange vectors and pull
// only the gap. A rejoining node catches up without replaying the world.
//
// NOTE on the dependency stack: @chainsafe/libp2p-gossipsub@14.1.2 depends
// on @libp2p/interface@^2.x internally, while libp2p's own latest major is
// v3 (@libp2p/interface@^3.x) — a real, currently-unresolved incompatibility
// in the js-libp2p ecosystem (gossipsub has not yet been updated for
// libp2p v3). package.json pins the whole stack to the last mutually
// compatible v2-line versions (verified via `npm ls @libp2p/interface`
// showing a single deduped 2.11.0). Do not bump these individually without
// re-checking that alignment — a caret-range `npm install` will happily
// reintroduce the split and gossipsub will silently never form a mesh
// (peers connect, but getSubscribers() stays empty forever; discovered the
// hard way). On this pinned v2 stack, Stream is the classic
// {source, sink} Duplex, verified empirically against the actual installed
// version rather than assumed from typings.
import { pipe } from "it-pipe";
import * as lp from "it-length-prefixed";
import { fromString as u8FromString, toString as u8ToString } from "uint8arrays";

export const SYNC_PROTOCOL = "/aether/sync/1.0.0";

// AbortSignal passed to dialProtocol only bounds connection setup — once a
// stream exists, a peer that accepts it and never sends data (or never
// closes) can hang a plain `pipe(stream.source, ...)` read forever. Found
// via Phase 5 chaos testing (a responder that accepts the stream and just
// never replies): the requester blocked indefinitely despite passing a
// `timeoutMs` all the way through, because nothing was actually enforcing
// it on the read. This wraps a promise with a real deadline; the caller is
// still responsible for closing the stream afterward so the loser of the
// race doesn't keep running forever in the background.
function withTimeout(promise, ms, message) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), ms);
  });
  // Swallow a late rejection/resolution from whichever side loses the
  // race — otherwise closing the stream afterward can surface as an
  // unhandled rejection here once the loser eventually settles.
  promise.catch(() => {});
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

// Responder side: a peer is pulling from us. Read their vector, send back
// whatever events they're missing, per our own ledger. Guards against a
// requester that dials and then never sends anything.
export function registerSyncHandler(libp2p, ledgerClient, logger, timeoutMs = 5000) {
  libp2p.handle(SYNC_PROTOCOL, async ({ stream }) => {
    try {
      await withTimeout(
        pipe(
          stream.source,
          (source) => lp.decode(source),
          async function* (source) {
            for await (const msg of source) {
              const vector = JSON.parse(u8ToString(msg.subarray()));
              const events = await ledgerClient.getEventsSince(vector);
              yield u8FromString(JSON.stringify(events));
            }
          },
          (source) => lp.encode(source),
          stream.sink,
        ),
        timeoutMs,
        `sync handler timed out after ${timeoutMs}ms waiting on requester`,
      );
    } catch (err) {
      logger.warn(`sync handler error: ${err.message}`);
    } finally {
      try {
        await stream.close();
      } catch {
        // Already closed.
      }
    }
  });
}

// Requester side: pull from `peerId` — send our vector, receive their gap
// events, merge them into our own ledger. Returns the count merged.
export async function pullFromPeer(libp2p, ledgerClient, peerId, timeoutMs, logger) {
  let stream;
  try {
    const localVector = await ledgerClient.getVector();
    stream = await libp2p.dialProtocol(peerId, SYNC_PROTOCOL, {
      signal: AbortSignal.timeout(timeoutMs),
    });

    await withTimeout(
      pipe([u8FromString(JSON.stringify(localVector))], (source) => lp.encode(source), stream.sink),
      timeoutMs,
      `sync write timed out after ${timeoutMs}ms`,
    );

    const responses = [];
    await withTimeout(
      pipe(stream.source, (source) => lp.decode(source), async (source) => {
        for await (const msg of source) {
          responses.push(msg.subarray());
        }
      }),
      timeoutMs,
      `sync read timed out after ${timeoutMs}ms — peer accepted the stream but never responded`,
    );

    if (responses.length === 0) {
      return 0;
    }
    const events = JSON.parse(u8ToString(responses[0]));
    const result = await ledgerClient.postEvents(events);
    return result.merged ?? 0;
  } catch (err) {
    logger.warn(`anti-entropy pull from ${peerId} failed: ${err.message}`);
    return 0;
  } finally {
    if (stream) {
      try {
        await stream.close();
      } catch {
        // Already closed by the remote or by the error above.
      }
    }
  }
}
