/** Cmd-K: jump to a project, map or ticket; New job, Message, the views, the projects' panels; and the two forms it opens. */
import { IconActivity, IconFolder, IconInbox, IconListNumbers, IconMail, IconMap2, IconMessage, IconTerminal2, IconTicket } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { tkey, agentLabel, agentOf, folder, poolOf, projOf, whenDelivered } from "@/lib/board.ts";
import { setLink } from "@/lib/link.ts";
import type { Sidebar } from "@/lib/sidebar.ts";
import { say } from "@/lib/notice.ts";
import { useBoard } from "./context.tsx";

export type Dialogs = { kind: "none" } | { kind: "command" } | { kind: "job" } | { kind: "message"; to: string };

export function CommandMenu({ open, onClose, go, tree }: { open: boolean; onClose: () => void; go: (d: Dialogs) => void; tree: Sidebar }): React.JSX.Element {
  const { state, tickets } = useBoard();
  const run = (fn: () => void): void => {
    onClose();
    fn();
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="overflow-hidden p-0" aria-describedby={undefined}>
        <DialogTitle className="sr-only">Commands</DialogTitle>
        <Command loop>
          <CommandInput placeholder="Type a command" />
          <CommandList>
            <CommandEmpty>No command matches.</CommandEmpty>
            <CommandGroup heading="Actions">
              <CommandItem onSelect={() => { go({ kind: "job" }); }}>
                <IconTerminal2 aria-hidden />
                New job
              </CommandItem>
              <CommandItem onSelect={() => { go({ kind: "message", to: "" }); }}>
                <IconMessage aria-hidden />
                Message a session or worker
              </CommandItem>
            </CommandGroup>
            <CommandGroup heading="Filter by project or map">
              <CommandItem value="everything clear the filter" onSelect={() => { run(() => { setLink({ project: "", map: "" }); }); }}>
                <IconFolder aria-hidden />
                Everything
              </CommandItem>
              {tree.projects.flatMap((p) => [
                <CommandItem key={p.project} value={`project ${p.project}`} onSelect={() => { run(() => { setLink({ project: p.project, map: "" }); }); }}>
                  <IconFolder aria-hidden />
                  <span className="truncate">{p.project}</span>
                </CommandItem>,
                ...[...p.maps, ...p.quiet].map((m) => (
                  <CommandItem key={m.map} value={`map ${m.map} ${m.title}`} onSelect={() => { run(() => { setLink({ project: p.project, map: m.map }); }); }}>
                    <IconMap2 aria-hidden />
                    <span className="truncate">{m.map}</span>
                  </CommandItem>
                )),
              ])}
            </CommandGroup>
            {(tickets ?? []).length > 0 && (
              <CommandGroup heading="Tickets">
                {(tickets ?? []).map((t) => (
                  <CommandItem key={tkey(t)} value={`ticket ${tkey(t)} ${t.title}`} onSelect={() => { run(() => { setLink({ t: tkey(t) }); }); }}>
                    <IconTicket aria-hidden />
                    <span className="truncate">{t.title}</span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">{`${t.map} #${String(t.num)}`}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            <CommandGroup heading="Go to">
              <CommandItem onSelect={() => { run(() => { setLink({ view: "runs" }); }); }}>
                <IconActivity aria-hidden />
                Runs
              </CommandItem>
              <CommandItem onSelect={() => { run(() => { setLink({ view: "queue" }); }); }}>
                <IconListNumbers aria-hidden />
                Queue
              </CommandItem>
              <CommandItem onSelect={() => { run(() => { setLink({ view: "waits" }); }); }}>
                <IconInbox aria-hidden />
                Waits for you
              </CommandItem>
            </CommandGroup>
            {Object.keys(state.providers).length > 0 && (
              <CommandGroup heading="Projects">
                {Object.keys(state.providers)
                  .sort((x, y) => folder(x).localeCompare(folder(y)))
                  .map((p) => (
                    <CommandItem key={p} value={`project ${folder(p)} ${p}`} onSelect={() => { run(() => { setLink({ t: `p:${p}` }); }); }}>
                      <IconFolder aria-hidden />
                      <span className="truncate">{folder(p) || p}</span>
                    </CommandItem>
                  ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

export function JobDialog({ open, onClose }: { open: boolean; onClose: () => void }): React.JSX.Element {
  const { state, tickets, queueWrite, down, busy } = useBoard();
  const [err, setErr] = useState<string | null>(null);
  const projects = [...new Set((tickets ?? []).map((t) => projOf(t.map)))].sort();
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent>
        <div>
          <DialogTitle>New job</DialogTitle>
          <DialogDescription>A one-off prompt, run headless like a ticket.</DialogDescription>
        </div>
        <form
          className="grid gap-3 sm:grid-cols-2"
          autoComplete="off"
          onSubmit={(ev) => {
            ev.preventDefault();
            const f = new FormData(ev.currentTarget);
            const val = (k: string): string => {
              const v = f.get(k);
              return typeof v === "string" ? v.trim() : "";
            };
            const project = val("project");
            const prompt = val("prompt");
            if (!project || !prompt) {
              setErr("A job needs a project and a prompt.");
              return;
            }
            setErr(null);
            void queueWrite(
              "POST /api/queue/job",
              { project, prompt, agent: val("agent") || null, model: val("model") || null, name: val("name") || null, at: val("at") || null },
              "Queued. It runs when the queue reaches it.",
            ).then((out) => {
              if (out.ok) onClose();
              else setErr(out.words);
            });
          }}
        >
          <Label className="sm:col-span-2">
            Project
            <Input name="project" list="sb-projects" required maxLength={500} placeholder="a wayfinder project, or a path to a git checkout" />
            <datalist id="sb-projects">
              {projects.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
          </Label>
          <Label className="sm:col-span-2">
            Prompt
            <Textarea name="prompt" rows={5} required maxLength={20000} placeholder="What the agent should do; it runs alone, with no one to ask" />
          </Label>
          <Label>
            Account
            <Select name="agent" defaultValue="">
              <option value="">{`Tonight's (${poolOf(state).join(", ")})`}</option>
              {Object.keys(state.installed).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </Label>
          <Label>
            Model
            <Input name="model" maxLength={80} placeholder="optional, e.g. opus" />
          </Label>
          <Label>
            Name
            <Input name="name" maxLength={80} placeholder="optional; names its run folder" />
          </Label>
          <Label>
            Not before
            <Input name="at" type="time" />
          </Label>
          {err !== null && (
            <p role="alert" className="text-sm text-destructive sm:col-span-2">
              {err}
            </p>
          )}
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={down || busy}>
              Queue the job
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function MessageDialog({ to, onClose }: { to: string | null; onClose: () => void }): React.JSX.Element {
  const { state, agents, writes, down } = useBoard();
  const [target, setTarget] = useState(to ?? "");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const a = target ? agentOf(state, target) : null;
  const groups = new Map<string, { id: string; label: string }[]>();
  const add = (g: string, id: string, label: string): void => {
    groups.set(g, [...(groups.get(g) ?? []), { id, label }]);
  };
  for (const s of agents.sessions) {
    add(folder(s.project) || "No project", s.agent, `${agentLabel(s)} (${s.state ?? ""})`);
    for (const k of agents.kids.get(s.agent) ?? []) if (k.state !== "done") add(folder(s.project) || "No project", k.agent, `↳ ${agentLabel(k)}`);
  }
  for (const i of state.queue.items.filter((x) => x.state === "running")) {
    if (agentOf(state, i.key)) add("Queue workers", i.key, i.title ?? i.key);
  }
  const send = async (): Promise<void> => {
    if (!target) {
      setErr("Pick who it is for first.");
      return;
    }
    if (!text.trim()) return;
    setSending(true);
    const out = await writes.send(target, text.trim());
    setSending(false);
    if (out.ok) {
      say({ ok: true, words: `Queued for ${a ? agentLabel(a) : target.slice(0, 6)}. ${whenDelivered(a)}` });
      onClose();
    } else setErr(out.words);
  };
  return (
    <Dialog
      open={to !== null}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent>
        <div>
          <DialogTitle className="flex items-center gap-2">
            <IconMail className="size-4" aria-hidden />
            Message
          </DialogTitle>
          <DialogDescription>{a ? whenDelivered(a) : "It reaches the session through its hooks."}</DialogDescription>
        </div>
        <form
          className="flex flex-col gap-3"
          onSubmit={(ev) => {
            ev.preventDefault();
            void send();
          }}
        >
          <Label>
            To
            <Select
              value={target}
              onChange={(ev) => {
                setTarget(ev.currentTarget.value);
              }}
            >
              <option value="">Pick a session or worker…</option>
              {[...groups].map(([g, list]) => (
                <optgroup key={g} label={g}>
                  {list.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </Select>
          </Label>
          <Label>
            Message
            <Textarea
              autoFocus={to !== ""}
              rows={4}
              maxLength={4000}
              value={text}
              placeholder="Enter sends, Shift-Enter starts a new line"
              onChange={(ev) => {
                setText(ev.currentTarget.value);
              }}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" && !ev.shiftKey && !ev.nativeEvent.isComposing) {
                  ev.preventDefault();
                  void send();
                }
              }}
            />
          </Label>
          {err !== null && (
            <p role="alert" className="text-sm text-destructive">
              {err}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={down || sending}>
              {sending ? "Sending…" : "Send"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
