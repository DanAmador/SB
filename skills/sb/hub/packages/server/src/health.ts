import { CONTRACT_VERSION, type Health } from "@sb-hub/contract";

export function health(): Health {
  return { ok: true, contract: CONTRACT_VERSION };
}
