/** Name of the hub API contract version. */
export const CONTRACT_VERSION = 0 as const;

export interface Health {
  readonly ok: boolean;
  readonly contract: typeof CONTRACT_VERSION;
}

export * from "./schemas.ts";
export * from "./routes.ts";
export * from "./runTicket.ts";
export * from "./links.ts";
export * from "./enrich.ts";
