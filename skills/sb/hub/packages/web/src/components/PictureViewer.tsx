/** A run's pictures at full size: arrows and keys step, scroll or + zooms, Esc closes, and the strip of every picture sits below. */
import { IconChevronLeft, IconChevronRight, IconX, IconZoomIn, IconZoomOut } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Dialog } from "@/components/ui/dialog";
import { mediaUrl } from "@/lib/api.ts";
import { clampZoom, stepIndex } from "@/lib/history.ts";
import { cn } from "@/lib/utils";

export const isClip = (n: string): boolean => /\.(mp4|webm)$/i.test(n);

export function PictureViewer({ runKey, names, name, onPick, onClose }: { runKey: string; names: readonly string[]; name: string; onPick: (n: string) => void; onClose: () => void }): React.JSX.Element {
  const found = names.indexOf(name);
  const at = found < 0 ? 0 : found;
  const current = names[at] ?? name;
  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <Stage key={current} runKey={runKey} names={names} at={at} current={current} onPick={onPick} />
    </Dialog>
  );
}

/** One picture; a new picture is a new Stage, so the zoom starts again at 1x. */
function Stage({ runKey, names, at, current, onPick }: { runKey: string; names: readonly string[]; at: number; current: string; onPick: (n: string) => void }): React.JSX.Element {
  const [zoom, setZoom] = useState(1);
  const clip = isClip(current);
  const go = (by: 1 | -1): void => {
    const n = names[stepIndex(at, by, names.length)];
    if (n !== undefined) onPick(n);
  };
  const zoomBy = (f: number): void => {
    setZoom((z) => clampZoom(z * f));
  };
  const onKeyDown = (ev: React.KeyboardEvent): void => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.key === "ArrowLeft") go(-1);
    else if (ev.key === "ArrowRight") go(1);
    else if (ev.key === "+" || ev.key === "=") zoomBy(1.25);
    else if (ev.key === "-" || ev.key === "_") zoomBy(0.8);
    else if (ev.key === "0") setZoom(1);
    else return;
    ev.preventDefault();
    ev.stopPropagation();
  };
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/85" />
      <DialogPrimitive.Content
        aria-describedby={undefined}
        onKeyDown={onKeyDown}
        className="fixed inset-0 z-50 flex flex-col bg-neutral-950 text-white outline-none"
      >
        <DialogPrimitive.Title className="sr-only">{`Picture ${String(at + 1)} of ${String(names.length)}: ${current}`}</DialogPrimitive.Title>
        <div className="flex items-center gap-2 px-3 py-2 text-sm">
          <span className="min-w-0 flex-1 truncate" title={current}>
            {current}
            <span className="text-white/60">{` · ${String(at + 1)} of ${String(names.length)}`}</span>
          </span>
          {!clip && (
            <>
              <button type="button" aria-label="Zoom out" title="Zoom out (-)" onClick={() => { zoomBy(0.8); }} className={BTN}><IconZoomOut className="size-5" aria-hidden /></button>
              <span aria-live="polite" className="w-12 text-center text-xs tabular-nums text-white/70">{`${String(Math.round(zoom * 100))}%`}</span>
              <button type="button" aria-label="Zoom in" title="Zoom in (+)" onClick={() => { zoomBy(1.25); }} className={BTN}><IconZoomIn className="size-5" aria-hidden /></button>
            </>
          )}
          <DialogPrimitive.Close aria-label="Close" title="Close (Esc)" className={BTN}><IconX className="size-5" aria-hidden /></DialogPrimitive.Close>
        </div>
        <div
          className={cn("relative flex min-h-0 flex-1 items-center justify-center", zoom > 1 ? "overflow-auto" : "overflow-hidden")}
          onWheel={(ev) => {
            if (!clip && ev.deltaY !== 0) zoomBy(ev.deltaY < 0 ? 1.15 : 1 / 1.15);
          }}
        >
          {clip ? (
            <video key={current} src={mediaUrl(runKey, current)} controls autoPlay playsInline aria-label={current} className="max-h-full max-w-full" />
          ) : (
            <img
              src={mediaUrl(runKey, current)}
              alt={current}
              draggable={false}
              style={zoom > 1 ? { width: `${String(zoom * 100)}%`, maxWidth: "none", maxHeight: "none", margin: "auto" } : undefined}
              className={cn("select-none", zoom === 1 && "max-h-full max-w-full object-contain")}
            />
          )}
          {names.length > 1 && (
            <>
              <button type="button" aria-label="Previous picture" title="Previous (←)" onClick={() => { go(-1); }} className={cn(BTN, "fixed top-1/2 left-2 size-10 -translate-y-1/2 bg-black/50")}><IconChevronLeft className="size-6" aria-hidden /></button>
              <button type="button" aria-label="Next picture" title="Next (→)" onClick={() => { go(1); }} className={cn(BTN, "fixed top-1/2 right-2 size-10 -translate-y-1/2 bg-black/50")}><IconChevronRight className="size-6" aria-hidden /></button>
            </>
          )}
        </div>
        <ul aria-label="Pictures of this run" className="flex shrink-0 justify-center gap-2 overflow-x-auto px-3 py-3">
          {names.map((n) => (
            <li key={n} className="shrink-0">
              <button
                type="button"
                aria-label={`Show ${n}`}
                aria-current={n === current ? "true" : undefined}
                onClick={() => { onPick(n); }}
                className={cn("block h-16 w-24 overflow-hidden rounded-md border-2 bg-white/10 focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none", n === current ? "border-white" : "border-transparent opacity-70 hover:opacity-100")}
              >
                {isClip(n) ? <video src={`${mediaUrl(runKey, n)}#t=0.1`} preload="metadata" muted playsInline className="size-full object-cover" /> : <img src={mediaUrl(runKey, n)} alt="" loading="lazy" className="size-full object-cover" />}
              </button>
            </li>
          ))}
        </ul>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

const BTN = "inline-flex size-8 shrink-0 items-center justify-center rounded-full text-white hover:bg-white/20 focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none";
