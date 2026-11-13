/** Name of the hub API contract version; real API types arrive in later tickets. */
export const CONTRACT_VERSION = 0 as const;

export interface Health {
  readonly ok: boolean;
  readonly contract: typeof CONTRACT_VERSION;
}
