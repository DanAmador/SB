/** The Python hub, run as this server's child on a port the OS picks (ruling on ticket 028, first cut). */
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { join } from "node:path";

export const SBHUB = new URL("../../../../scripts/sbhub.py", import.meta.url).pathname;
const READY = /^sb hub on http:\/\/127\.0\.0\.1:(\d+)$/;

export interface PythonHub {
  readonly child: ChildProcess;
  readonly port: number;
}

/**
 * A Python hub left by a server that died without stopping it (SIGKILL) is killed the way
 * `sbhub_service.sh --take-over` kills one: SIGKILL, so its workers live on and the new hub adopts them.
 */
export function reapStale(pidFile: string): void {
  let pid: number;
  try {
    pid = Number.parseInt(readFileSync(pidFile, "utf8"), 10);
  } catch {
    return;
  }
  if (!Number.isInteger(pid) || pid <= 1) return;
  let command: string;
  try {
    command = execFileSync("ps", ["-o", "command=", "-p", String(pid)], { encoding: "utf8" });
  } catch {
    return; // not running
  }
  if (!command.includes("sbhub.py serve")) return;
  try {
    process.kill(pid, "SIGKILL");
  } catch {
    // already gone
  }
}

/** Starts `sbhub.py serve --port 0` and resolves once it names its port; its later output goes to ours. */
export function startPython(home: string, python = process.env.SB_HUB_PYTHON ?? "python3"): Promise<PythonHub> {
  const pidFile = join(home, "hub-python.pid");
  reapStale(pidFile);
  const child = spawn(python, [SBHUB, "serve", "--port", "0"], { stdio: ["ignore", "pipe", "inherit"], env: process.env });
  return new Promise((resolve, reject) => {
    const lines = createInterface({ input: child.stdout });
    let up = false;
    lines.on("line", (line) => {
      const m = READY.exec(line.trim());
      if (!up && m?.[1] !== undefined) {
        up = true;
        if (child.pid !== undefined) writeFileSync(pidFile, `${String(child.pid)}\n`);
        child.once("exit", () => { rmSync(pidFile, { force: true }); });
        resolve({ child, port: Number(m[1]) });
        return;
      }
      process.stdout.write(`${line}\n`);
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (!up) reject(new Error(`the Python hub exited (${String(code)}) before it started`));
    });
  });
}
