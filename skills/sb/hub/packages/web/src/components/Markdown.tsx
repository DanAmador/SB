/** A report's Markdown as React nodes: headings, lists, quotes, fenced code, tables, bold, italics, code and links. No HTML is ever passed through. */
import type * as React from "react";
import { cn } from "@/lib/utils";

const SAFE = /^(https?:|obsidian:|mailto:)/i;

/** Inline `code`, **bold**, *italic*, [text](url) and [[wikilink]] in one line. */
function inline(text: string, at: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*|\[([^\]]+)\]\(([^)\s]+)\)|\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;
  let last = 0;
  let n = 0;
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${at}.${String(n++)}`;
    if (m[1] !== undefined) out.push(<code key={k} className="rounded bg-muted px-1 py-px font-mono text-[0.85em]">{m[1]}</code>);
    else if (m[2] !== undefined) out.push(<strong key={k}>{m[2]}</strong>);
    else if (m[3] !== undefined) out.push(<em key={k}>{m[3]}</em>);
    else if (m[4] !== undefined && m[5] !== undefined) {
      out.push(SAFE.test(m[5]) ? <a key={k} href={m[5]} className="text-brand underline-offset-2 hover:underline">{m[4]}</a> : <span key={k}>{m[4]}</span>);
    } else out.push(<span key={k}>{m[7] ?? m[6] ?? ""}</span>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = (line: string): string[] => line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());

export function Markdown({ text, className }: { text: string; className?: string }): React.JSX.Element {
  const body = text.replace(/^---\n[\s\S]*?\n---\n/, "");
  const lines = body.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    const key = String(i);
    const fence = /^\s*(```|~~~)/.exec(line);
    if (fence) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? "").trimStart().startsWith(fence[1] ?? "```")) code.push(lines[i++] ?? "");
      i++;
      blocks.push(<pre key={key} className="overflow-auto rounded-md bg-muted p-2 font-mono text-xs whitespace-pre-wrap">{code.join("\n")}</pre>);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = (h[1] ?? "#").length;
      const cls = level === 1 ? "text-lg font-semibold" : level === 2 ? "mt-2 text-base font-semibold" : "mt-1 text-sm font-semibold";
      blocks.push(<p key={key} role="heading" aria-level={level} className={cls}>{inline(h[2] ?? "", key)}</p>);
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push(<hr key={key} className="my-1" />);
      i++;
      continue;
    }
    if (line.trimStart().startsWith("|") && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && (lines[i] ?? "").trimStart().startsWith("|")) rows.push(cells(lines[i++] ?? ""));
      blocks.push(
        <div key={key} className="overflow-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead><tr>{head.map((c, n) => <th key={n} className="border-b px-2 py-1 font-medium">{inline(c, `${key}h${String(n)}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, n) => <tr key={n}>{r.map((c, m) => <td key={m} className="border-b px-2 py-1 align-top">{inline(c, `${key}r${String(n)}${String(m)}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i] ?? "")) quote.push((lines[i++] ?? "").replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={key} className="border-l-2 pl-3 text-muted-foreground">{inline(quote.join(" "), key)}</blockquote>);
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i] ?? "")) {
        const raw = lines[i++] ?? "";
        const depth = Math.min(3, Math.floor((/^\s*/.exec(raw)?.[0].length ?? 0) / 2));
        const task = /^\s*[-*]\s+\[([ xX])\]\s+(.*)$/.exec(raw);
        const textOf = task ? (task[2] ?? "") : raw.replace(/^\s*([-*]|\d+\.)\s+/, "");
        // a lazy continuation line (indented, not a bullet) belongs to the item above
        let more = "";
        while (i < lines.length && /^\s{2,}\S/.test(lines[i] ?? "") && !/^\s*([-*]|\d+\.)\s+/.test(lines[i] ?? "") && !(lines[i] ?? "").trimStart().startsWith("```")) more += ` ${(lines[i++] ?? "").trim()}`;
        items.push(
          <li key={i} style={{ marginLeft: `${String(depth)}rem` }}>
            {task && <span aria-hidden>{task[1] === " " ? "☐ " : "☑ "}</span>}
            {inline(textOf + more, String(i))}
          </li>,
        );
      }
      blocks.push(ordered ? <ol key={key} className="list-decimal pl-5">{items}</ol> : <ul key={key} className="list-disc pl-5">{items}</ul>);
      continue;
    }
    if (line.trim() === "") {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && (lines[i] ?? "").trim() !== "" && !/^(#{1,6}\s|\s*(```|~~~)|\s*>|\s*([-*]|\d+\.)\s+)/.test(lines[i] ?? "")) para.push(lines[i++] ?? "");
    if (para.length === 0) {
      para.push(lines[i++] ?? "");
    }
    blocks.push(<p key={key}>{inline(para.join(" "), key)}</p>);
  }
  return <div className={cn("flex flex-col gap-2 text-sm leading-relaxed break-words", className)}>{blocks}</div>;
}
