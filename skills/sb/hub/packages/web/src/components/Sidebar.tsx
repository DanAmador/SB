/** The sidebar: Everything, then each project with its maps (collapsible, one list, busiest first), each row with can-run and queued counts. On a phone it is a sheet. */
import { IconChevronDown, IconChevronRight, IconFilter, IconMenu2, IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { isScoped, type Scope } from "@/lib/board.ts";
import { activeOnly, type Counts, type Sidebar as Tree, type SidebarMap } from "@/lib/sidebar.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { cn } from "@/lib/utils";

const rowCls = (on: boolean): string =>
  cn(
    "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
    on && "bg-accent font-medium",
  );

/** Can run now · queued; a zero is dimmed so the non-zero ones stand out. */
function CountPair({ c }: { c: Counts }): React.JSX.Element {
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs tabular-nums">
      <span className={cn("min-w-4 text-right", c.canRun > 0 ? "font-medium text-foreground" : "text-muted-foreground")} title={`${String(c.canRun)} can run now`} aria-label={`${String(c.canRun)} can run now`}>
        {c.canRun}
      </span>
      <span className={cn("min-w-4 text-right", c.queued > 0 ? "font-medium text-foreground" : "text-muted-foreground")} title={`${String(c.queued)} queued`} aria-label={`${String(c.queued)} queued`}>
        {c.queued}
      </span>
    </span>
  );
}

/** A green dot beside a name when a worker runs there. */
function Dot({ on }: { on: boolean }): React.JSX.Element | null {
  return on ? <span role="img" aria-label="running" title="a worker is running" className="size-2 shrink-0 rounded-full bg-ok" /> : null;
}

function MapRow({ m, project, on, pick }: { m: SidebarMap; project: string; on: boolean; pick: (p: string, m: string) => void }): React.JSX.Element {
  return (
    <div className="flex pl-6">
      <button type="button" aria-current={on ? "page" : undefined} title={m.map} className={rowCls(on)} onClick={() => { pick(project, m.map); }}>
        <span className="truncate text-muted-foreground">{m.title}</span>
        {m.reason !== "" && <span className="shrink-0 text-xs text-muted-foreground">{m.reason}</span>}
        <Dot on={m.running} />
        <CountPair c={m} />
      </button>
    </div>
  );
}

function ProjectTree({ tree: whole, scope, onPick }: { tree: Tree; scope: Scope; onPick: () => void }): React.JSX.Element {
  const active = useLink().act === "1";
  const tree = active ? activeOnly(whole, scope) : whole;
  const [shut, setShut] = useState<ReadonlySet<string>>(new Set());
  const flip = (set: ReadonlySet<string>, p: string): Set<string> => {
    const n = new Set(set);
    if (n.has(p)) n.delete(p);
    else n.add(p);
    return n;
  };
  const toggle = (p: string): void => {
    setShut((s) => flip(s, p));
  };
  const pick = (project: string, map: string): void => {
    setLink({ project, map });
    onPick();
  };
  return (
    <nav aria-label="Projects and maps" className="flex flex-col gap-0.5 text-sm">
      <div className="flex items-center px-2 pb-1 text-[11px] text-muted-foreground">
        <button
          type="button"
          role="switch"
          aria-checked={active}
          title="Show only the projects and maps with something running or queued"
          onClick={() => { setLink({ act: active ? "" : "1" }); }}
          className={cn(
            "inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-[11px] transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            active ? "border-foreground bg-foreground text-background" : "hover:text-foreground",
          )}
        >
          <IconFilter className="size-3" aria-hidden />
          Active only
        </button>
        <span className="ml-auto">can run · queued</span>
      </div>
      <div className="flex">
        <button type="button" aria-current={!isScoped(scope) ? "page" : undefined} className={rowCls(!isScoped(scope))} onClick={() => { pick("", ""); }}>
          <span className="truncate">Everything</span>
          <Dot on={tree.all.running} />
          <CountPair c={tree.all} />
        </button>
      </div>
      {active && tree.projects.length === 0 && <p className="px-2 py-1.5 text-xs text-muted-foreground">Nothing is running or queued.</p>}
      {tree.projects.map((p) => {
        const open = !shut.has(p.project) || scope.project === p.project;
        const onProject = scope.project === p.project && scope.map === "";
        return (
          <div key={p.project} className="flex flex-col">
            <div className="flex items-center">
              <button
                type="button"
                aria-label={`${open ? "Collapse" : "Expand"} ${p.project}`}
                aria-expanded={open}
                className="rounded-md p-1 text-muted-foreground hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                onClick={() => { toggle(p.project); }}
              >
                {open ? <IconChevronDown className="size-3.5" aria-hidden /> : <IconChevronRight className="size-3.5" aria-hidden />}
              </button>
              <button type="button" aria-current={onProject ? "page" : undefined} className={rowCls(onProject)} onClick={() => { pick(p.project, ""); }}>
                <span className="truncate">{p.project}</span>
                <Dot on={p.running} />
                <CountPair c={p} />
              </button>
            </div>
            {open && p.maps.map((m) => <MapRow key={m.map} m={m} project={p.project} on={scope.map === m.map} pick={pick} />)}
          </div>
        );
      })}
    </nav>
  );
}

/** The wide screen's column. */
export function SidebarColumn({ tree, scope }: { tree: Tree; scope: Scope }): React.JSX.Element {
  return (
    <aside aria-label="Sidebar" className="sticky top-[57px] hidden h-[calc(100dvh-57px)] w-64 shrink-0 overflow-y-auto border-r px-2 py-3 lg:block">
      <ProjectTree tree={tree} scope={scope} onPick={() => undefined} />
    </aside>
  );
}

/** The phone's sheet behind the menu button. */
export function SidebarSheet({ tree, scope, open, onOpenChange }: { tree: Tree; scope: Scope; open: boolean; onOpenChange: (o: boolean) => void }): React.JSX.Element {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="right-auto left-0 w-72 max-w-[85vw] sm:max-w-xs sm:border-r sm:border-l-0 data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left">
        <div className="border-b px-4 pt-5 pb-3">
          <SheetTitle>Projects</SheetTitle>
          <SheetDescription>Pick one to narrow every view.</SheetDescription>
        </div>
        <div className="flex-1 overflow-y-auto px-2 py-3">
          <ProjectTree
            tree={tree}
            scope={scope}
            onPick={() => {
              onOpenChange(false);
            }}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function MenuButton({ onClick }: { onClick: () => void }): React.JSX.Element {
  return (
    <button
      type="button"
      aria-label="Projects and maps"
      onClick={onClick}
      className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none lg:hidden"
    >
      <IconMenu2 className="size-5" aria-hidden />
    </button>
  );
}

/** The breadcrumb on top: Everything / project / map, with an x that clears it. Nothing when nothing is picked. */
export function Breadcrumb({ scope }: { scope: Scope }): React.JSX.Element | null {
  if (!isScoped(scope)) return null;
  const crumb = "rounded px-1 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-muted-foreground">
      <button type="button" className={crumb} onClick={() => { setLink({ project: "", map: "" }); }}>
        Everything
      </button>
      <span aria-hidden>/</span>
      {scope.map === "" ? (
        <span className="px-1 font-medium text-foreground" aria-current="location">{scope.project}</span>
      ) : (
        <>
          <button type="button" className={crumb} onClick={() => { setLink({ project: scope.project, map: "" }); }}>
            {scope.project}
          </button>
          <span aria-hidden>/</span>
          <span className="px-1 font-medium text-foreground" aria-current="location">{scope.map.split("/").pop()}</span>
        </>
      )}
      <button
        type="button"
        aria-label="Clear the filter"
        title="Clear the filter"
        className="ml-1 inline-flex size-6 items-center justify-center rounded-md hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        onClick={() => { setLink({ project: "", map: "" }); }}
      >
        <IconX className="size-3.5" aria-hidden />
      </button>
    </nav>
  );
}
