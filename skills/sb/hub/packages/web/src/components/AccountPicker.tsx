/** Which account launches one ticket: the run's accounts by default, or one installed account. */
import { IconCheck, IconChevronDown, IconRobot } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { accountState, poolOf } from "@/lib/board.ts";
import { cn } from "@/lib/utils";
import { useBoard } from "./context.tsx";

export function AccountList({ chosen, onPick }: { chosen: string | null; onPick: (name: string | null) => void }): React.JSX.Element {
  const { state } = useBoard();
  const pool = poolOf(state);
  const options: [string | null, string, string][] = [
    [null, "The run's accounts", pool.join(", ") || "none chosen"],
    ...Object.entries(state.installed).map(([n, e]): [string, string, string] => [n, n, accountState(n, e, state).words]),
  ];
  return (
    <ul role="listbox" aria-label="Account" className="flex flex-col gap-0.5">
      {options.map(([name, label, hint]) => (
        <li key={name ?? ""} role="option" aria-selected={chosen === name}>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent focus-visible:bg-accent"
            onClick={() => {
              onPick(name);
            }}
          >
            <IconCheck className={cn("size-4 shrink-0", chosen === name ? "text-brand" : "invisible")} aria-hidden />
            <span className="font-medium">{label}</span>
            <span className="ml-auto truncate text-xs text-muted-foreground">{hint}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** The account a queued item runs on, shown once on its line; a click changes it. */
export function AccountPicker({ itemKey, chosen, title }: { itemKey: string; chosen: string | null; title: string }): React.JSX.Element {
  const { queueWrite, down, busy } = useBoard();
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="xs"
          disabled={down || busy}
          aria-label={`${chosen ?? "pool"}: the account for ${title}`}
          className={cn("h-6 max-w-36 gap-1 px-1.5 font-normal", chosen !== null ? "text-brand" : "text-muted-foreground")}
        >
          <IconRobot aria-hidden />
          <span className="truncate">{chosen ?? "pool"}</span>
          <IconChevronDown className="size-3!" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-1.5">
        <AccountList
          chosen={chosen}
          onPick={(name) => {
            setOpen(false);
            if (name !== chosen) {
              void queueWrite("POST /api/queue/item_agent", { key: itemKey, name }, name === null ? "It runs on the run's accounts." : `It runs on ${name}.`);
            }
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

/** Queue, with a menu beside it to queue on one account. */
export function QueueButton({ itemKey, title }: { itemKey: string; title: string }): React.JSX.Element {
  const { enqueue, queueWrite, down, busy } = useBoard();
  const [open, setOpen] = useState(false);
  const off = down || busy;
  return (
    <div className="flex shrink-0">
      <Button
        size="xs"
        variant="outline"
        disabled={off}
        className="rounded-r-none"
        aria-label={`Queue ${title}`}
        onClick={() => {
          void enqueue(itemKey);
        }}
      >
        Queue
      </Button>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button size="xs" variant="outline" disabled={off} className="-ml-px rounded-l-none px-1" aria-label={`Queue ${title} on an account`}>
            <IconChevronDown aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-1.5">
          <p className="px-2 py-1 text-xs text-muted-foreground">Queue it on</p>
          <AccountList
            chosen={null}
            onPick={(name) => {
              setOpen(false);
              void enqueue(itemKey).then(() => {
                if (name !== null) void queueWrite("POST /api/queue/item_agent", { key: itemKey, name }, `Queued on ${name}.`);
              });
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
