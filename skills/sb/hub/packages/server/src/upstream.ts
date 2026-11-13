/** One request to the Python hub on its internal port, read whole (media stay small, as the hub reads them whole too). */
import { request } from "node:http";
import type { Answer } from "./check.ts";

export interface Forward {
  readonly method: string;
  /** Path and query, as the caller sent them. */
  readonly path: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly body?: Buffer;
}

export interface Reply extends Answer {
  readonly headers: Readonly<Record<string, string>>;
}

/** Headers passed back to the caller as the hub sent them. */
const KEPT = ["accept-ranges", "content-range"] as const;

export type Upstream = (f: Forward) => Promise<Reply>;

/** Forwards to 127.0.0.1:port, naming the hub's own Host (it refuses any other). No timeout: the hub answers or closes. */
export function upstream(port: () => number | undefined): Upstream {
  return (f) =>
    new Promise((resolve, reject) => {
      const p = port();
      if (p === undefined) {
        reject(new Error("the Python hub is not up yet"));
        return;
      }
      const headers: Record<string, string> = { ...f.headers, host: `127.0.0.1:${String(p)}` };
      if (f.body !== undefined) headers["content-length"] = String(f.body.length);
      const req = request({ host: "127.0.0.1", port: p, method: f.method, path: f.path, headers }, (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("error", reject);
        res.on("end", () => {
          const kept: Record<string, string> = {};
          for (const k of KEPT) {
            const v = res.headers[k];
            if (typeof v === "string") kept[k] = v;
          }
          resolve({ status: res.statusCode ?? 502, contentType: res.headers["content-type"] ?? "", body: Buffer.concat(chunks), headers: kept });
        });
      });
      req.on("error", reject);
      req.end(f.body);
    });
}
