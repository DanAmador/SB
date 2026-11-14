/** Where the hub listens and keeps its state, read as sbhub.py reads them. */
import { homedir } from "node:os";
import { join } from "node:path";

export const DEFAULT_PORT = 8765;

const valid = (n: number): boolean => Number.isInteger(n) && n > 0 && n < 65536;

/** --port N, else SB_HUB_PORT, else 8765; a value that is not a port falls back to 8765, as in sbhub.py. */
export function hubPort(argv: readonly string[], env: Readonly<Record<string, string | undefined>>): number {
  const i = argv.indexOf("--port");
  const given = i >= 0 ? argv[i + 1] : env.SB_HUB_PORT;
  if (given === undefined || given === "") return DEFAULT_PORT;
  const n = Number(given);
  return valid(n) ? n : DEFAULT_PORT;
}

export function hubHome(env: Readonly<Record<string, string | undefined>>): string {
  const h = env.SB_HUB_HOME;
  return h !== undefined && h !== "" ? h : join(homedir(), ".sb-hub");
}

/** The one extra address the hub listens on, and the secret its requests need. */
export interface Phone {
  readonly address: string;
  readonly secret: string;
}

const IPV4 = /^(?:\d{1,3}\.){3}\d{1,3}$/;

/**
 * SB_HUB_PHONE_ADDRESS (the Mac's address on the home Wi-Fi, e.g. 192.168.1.20) with SB_HUB_PHONE_SECRET. Off (undefined)
 * unless the address is set; an address without a secret, or that is not an IPv4 address, is an error, never a hub open to the Wi-Fi.
 */
export function phoneSetting(env: Readonly<Record<string, string | undefined>>): Phone | undefined {
  const address = env.SB_HUB_PHONE_ADDRESS?.trim() ?? "";
  if (address === "") return undefined;
  if (!IPV4.test(address) || address.split(".").some((n) => Number(n) > 255)) throw new Error(`SB_HUB_PHONE_ADDRESS must be an IPv4 address, not "${address}"`);
  if (address === "0.0.0.0" || address.startsWith("127.")) throw new Error("SB_HUB_PHONE_ADDRESS must be the Mac's address on the Wi-Fi, not 0.0.0.0 or a loopback address");
  const secret = env.SB_HUB_PHONE_SECRET ?? "";
  if (secret.length < 16) throw new Error("SB_HUB_PHONE_ADDRESS needs SB_HUB_PHONE_SECRET of at least 16 characters");
  return { address, secret };
}
