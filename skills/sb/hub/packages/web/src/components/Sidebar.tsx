/** The sidebar: Everything, then each project with its maps (collapsible), each row with two counts. On a phone it is a sheet. */
import { IconChevronDown, IconChevronRight, IconMenu2, IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { isScoped, type Counts, type Scope, type Sidebar as Tree } from "@/lib/board.ts";
import { setLink } from "@/lib/link.ts";
import { cn } from "@/lib/utils";

const rowCls = (on: boolean): string =>
  cn(
    "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
    on && "bg-accent font-medium",
  );

/** Running (green) and waiting for you (red); a zero is dimmed so the non-zero ones stand out. */
function CountPair({ c }: { c: Counts }): React.JSX.Element {
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs tabular-nums">
      <span className={cn("min-w-4 text-right", c.running > 0 ? "text-ok" : "text-muted-foreground")} title={`${String(c.running)} running`} aria-label={`${String(c.running)} running`}>
        {c.running}
      </span>
      <span className={cn("min-w-4 text-right", c.waiting > 0 ? "font-medium text-destructive" : "text-muted-foreground")} title={`${String(c.waiting)} waiting for you`} aria-label={`${String(c.waiting)} waiting for you`}>
        {c.waiting}
      </span>
    </span>
  );
}

function ProjectTree({ tree, scope, onPick }: { tree: Tree; scope: Scope; onPick: () => void }): React.JSX.Element {
  const [shut, setShut] = useState<ReadonlySet<string>>(new Set());
  const toggle = (p: string): void => {
    setShut((s) => {
      const n = new Set(s);
      if (n.has(p)) n.delete(p);
      else n.add(p);
      return n;
    });
  };
  const pick = (project: string, map: string): void => {
    setLink({ project, map });
    onPick();
  };
  return (
    <nav aria-label="Projects and maps" className="flex flex-col gap-0.5 text-sm">
      <div className="flex px-2 pb-1 text-[11px] text-muted-foreground">
        <span className="ml-auto">running · waiting</span>
      </div>
      <div className="flex">
        <button type="button" aria-current={!isScoped(scope) ? "page" : undefined} className={rowCls(!isScoped(scope))} onClick={() => { pick("", ""); }}>
          <span className="truncate">Everything</span>
          <CountPair c={tree.all} />
        </button>
      </div>
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
                <CountPair c={p} />
              </button>
            </div>
            {open &&
              p.maps.map((m) => {
                const on = scope.map === m.map;
                return (
                  <div key={m.map} className="flex pl-6">
                    <button type="button" aria-current={on ? "page" : undefined} title={m.map} className={rowCls(on)} onClick={() => { pick(p.project, m.map); }}>
                      <span className="truncate text-muted-foreground">{m.title}</span>
                      <CountPair c={m} />
                    </button>
                  </div>
                );
              })}
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
