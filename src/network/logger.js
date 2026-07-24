import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

// CLAUDE.md: "Fail loud and local: log to disk with the node_id, never
// swallow an exception to keep a loop alive silently."
export class Logger {
  constructor(nodeId, logPath) {
    this.nodeId = nodeId;
    this.logPath = logPath;
    mkdirSync(dirname(logPath), { recursive: true });
  }

  _write(level, message) {
    const line = `${new Date().toISOString()} [${this.nodeId}] ${level} ${message}`;
    console.log(line);
    try {
      appendFileSync(this.logPath, line + "\n", "utf-8");
    } catch {
      // Disk write failed — already on console, nothing more to do without
      // risking an infinite failure loop.
    }
  }

  info(message) {
    this._write("INFO", message);
  }

  warn(message) {
    this._write("WARN", message);
  }

  error(message) {
    this._write("ERROR", message);
  }
}
