/** The run's graph in the layout chosen in Settings: vertical (time down, the default the owner chose on
 * 2026-11-19) or horizontal (15-minute columns, time across). */
import type * as React from "react";
import type { Night, QueueItem } from "@sb-hub/contract";
import { useGraphLayout } from "@/lib/layout.ts";
import { NightGraphAcross } from "./NightGraphAcross.tsx";
import { NightGraphDown } from "./NightGraphDown.tsx";

export function NightGraph(props: { items?: readonly QueueItem[]; title?: string; frozen?: Pick<Night, "maps" | "repos" | "ended"> }): React.JSX.Element | null {
  return useGraphLayout() === "horizontal" ? <NightGraphAcross {...props} /> : <NightGraphDown {...props} />;
}
