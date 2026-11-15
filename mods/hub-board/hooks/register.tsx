/**
 * hub-board: `/board` opens the sb hub's night in a pane: what runs, what is queued, the questions waiting (answer
 * with one press) and the failed runs not looked at (Seen with one press). A pane is drawn by the app, the phone's
 * Mods sheet included, and never goes to the model. It reads the hub on 127.0.0.1:8765 every 30 seconds once
 * opened. `/board 10` lists the next 10 tickets (5 by default) with when each should start and its model;
 * `/board -10` lists the last 10 that landed instead. Each `/board` also sends the pictures and clips of up to 3
 * landed runs not sent yet, newest first, as file cards (they reach the phone too).
 */
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Ask, Board, Row } from '../types'

const HUB = 'http://127.0.0.1:8765'
const PANE = 'hub-board'
const EVERY_MS = 30_000

const EMPTY: Board = { at: 0, error: '', paused: false, running: [], upcoming: [], history: [], recent: [], landed: 0, next: 0, done: 0, failed: [], questions: [] }
// Change the tag when Board's fields change: it declines what an earlier version stored.
const board = atom({ plugin: 'hub-board', key: 'board' } as const, EMPTY, { shape: 'board-4' })
// The landed runs whose pictures were sent this session (`<key>@<landed time>`), so each is sent once.
const sent = atom({ plugin: 'hub-board', key: 'sent' } as const, [] as string[], { shape: 'sent-2' })
/** Runs whose pictures one `/board` sends, and pictures per run. */
const SEND_RUNS = 3
const SEND_FILES = 6

type Item = {
  key: string
  kind?: string
  state: string
  title?: string | null
  note?: string | null
  model?: string | null
  started?: number | null
  ended?: number | null
  night?: string | null
  repo?: string | null
  verdict?: string | null
  run?: string | null
  spend?: { run_minutes?: number | null } | null
}
/** What the queue does not carry for a ticket not started yet: its title, tier and repo, from /api/tickets. */
type Info = { title: string; tier: string; repo: string }
type TicketRow = { map: string; num: number; title?: string; tier?: string | null; repo?: string | null }
type Question = { q: string; options: string[]; default: string; deadline: number; answer: string | null }
type HubState = {
  now: number
  seen?: string[]
  questions?: Record<string, Question>
  queue: { paused?: boolean; night?: string | null; agents?: string[] | null; items: Item[]; cleared?: Item[] }
}

const firstLine = (s: string | null | undefined): string => (s ?? '').split('\n', 1)[0]?.trim() ?? ''
const titleOf = (i: Item, info?: Info): string => i.title?.trim() || info?.title || i.key
/** A clock time, HH:MM, in this machine's zone. */
export const hm = (secs: number): string => {
  const d = new Date(secs * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
/** The hub page's estimate of one ticket's run when tonight has none to learn from: 1.5 h. */
const ESTIMATE = 5400

/** How long a ticket runs tonight: the median of tonight's finished runs, else the hub's 1.5 h. */
export function typical(items: readonly Item[]): number {
  const d = items
    .filter(i => i.state === 'done' && i.started != null && i.ended != null && i.ended > i.started)
    .map(i => (i.ended ?? 0) - (i.started ?? 0))
    .sort((a, b) => a - b)
  return d.length === 0 ? ESTIMATE : (d[Math.floor(d.length / 2)] ?? ESTIMATE)
}

/**
 * When the running tickets end and the next `n` queued tickets start: the accounts run side by side, one ticket per
 * account, and a repo runs one ticket at a time; every ticket takes `typical` seconds. A guess, said with a ~.
 */
export function forecast(s: HubState, info: ReadonlyMap<string, Info>, n: number): { ends: Map<string, number>; starts: [Item, number][] } {
  const d = typical(s.queue.items)
  const repoOf = (i: Item): string => i.repo ?? info.get(i.key)?.repo ?? i.key.split('/')[0] ?? i.key
  const free: number[] = Array.from({ length: Math.max(1, s.queue.agents?.length ?? 1) }, () => s.now)
  const repoFree = new Map<string, number>()
  const take = (until: number, repo: string): void => {
    free[free.indexOf(Math.min(...free))] = until
    repoFree.set(repo, Math.max(repoFree.get(repo) ?? 0, until))
  }
  const ends = new Map<string, number>()
  for (const i of s.queue.items.filter(x => x.state === 'running' || x.state === 'review' || x.state === 'recheck')) {
    const end = Math.max(s.now, (i.started ?? s.now) + d)
    ends.set(i.key, end)
    take(end, repoOf(i))
  }
  const starts: [Item, number][] = []
  for (const i of s.queue.items.filter(x => x.state === 'queued' && x.kind !== 'job').slice(0, n)) {
    const at = Math.max(Math.min(...free), repoFree.get(repoOf(i)) ?? s.now)
    take(at + d, repoOf(i))
    starts.push([i, at])
  }
  return { ends, starts }
}
const mins = (secs: number): string => (secs < 60 ? 'just now' : secs < 3600 ? `${Math.round(secs / 60)} min` : `${(secs / 3600).toFixed(1)} h`)

/** The hub's state cut down to what the pane shows, by the same rules as the hub page's Waits for you. */
/**
 * The last `n` tickets that landed, newest first: judged done (✓) or landed and waiting for the review (◐). A landed
 * run has no end time yet, so its start plus its run minutes stands in.
 */
export function landedRuns(s: HubState, info: ReadonlyMap<string, Info>, n: number): Row[] {
  const at = (i: Item): number => i.ended ?? (i.started ?? 0) + (i.spend?.run_minutes ?? 0) * 60
  return [...s.queue.items, ...(s.queue.cleared ?? [])]
    .filter(i => i.kind !== 'job' && (i.state === 'done' || i.state === 'landed'))
    .sort((a, b) => at(b) - at(a))
    .slice(0, n)
    .map(i => {
      const took = i.started != null ? `${String(Math.round((at(i) - i.started) / 60))}m` : ''
      const judged = i.verdict != null && i.verdict !== 'finished' ? ` ${i.verdict}` : ''
      const num = i.key.split('#')[1]
      return {
        key: i.key,
        title: titleOf(i, info.get(i.key)),
        detail: [i.state === 'done' ? '✓' : '◐', hm(at(i)), i.model ?? '', took].filter(Boolean).join(' ') + judged,
        seen: `${i.key}@${String(Math.round(at(i)))}`,
        ...(i.run && num ? { media: `${i.run}/${num}-media` } : {}),
      }
    })
}

export function summarize(s: HubState, info: ReadonlyMap<string, Info> = new Map(), n = 5, back = 0): Board {
  const items = s.queue.items
  const { ends, starts } = forecast(s, info, n)
  const seen = new Set(s.seen ?? [])
  const seenKey = (i: Item): string => `${i.key}@${String(i.ended ?? 0)}`
  const running: Row[] = items
    .filter(i => i.state === 'running' || i.state === 'review' || i.state === 'recheck')
    .map(i => ({ key: i.key, title: titleOf(i, info.get(i.key)), detail: [i.state === 'running' ? '' : i.state, i.model ?? '', i.started ? mins(s.now - i.started) : '', `ends ~${hm(ends.get(i.key) ?? s.now)}`].filter(Boolean).join(' · ') }))
  const upcoming: Row[] = starts.map(([i, at]) => ({ key: i.key, title: titleOf(i, info.get(i.key)), detail: `~${hm(at)} ${i.model ?? info.get(i.key)?.tier ?? '?'}` }))
  const failed: Row[] = items
    .filter(i => (i.state === 'failed' || i.state === 'skipped') && !seen.has(seenKey(i)))
    // a run skipped because its ticket closed asks nothing of you (the page leaves it out too)
    .filter(i => !(i.state === 'skipped' && (i.note ?? '').startsWith('no longer open')))
    .sort((a, b) => (b.ended ?? 0) - (a.ended ?? 0))
    .map(i => ({ key: i.key, title: titleOf(i, info.get(i.key)), detail: firstLine(i.note).slice(0, 140) || i.state, seen: seenKey(i) }))
  const questions: Ask[] = Object.entries(s.questions ?? {})
    .filter(([, q]) => q.answer === null)
    .sort(([, a], [, b]) => a.deadline - b.deadline)
    .map(([id, q]) => ({ id, text: q.q, options: q.options, fallback: q.default, left: Math.max(0, q.deadline - s.now) }))
  return {
    at: s.now,
    error: '',
    paused: s.queue.paused === true,
    running,
    upcoming,
    history: landedRuns(s, info, back),
    recent: landedRuns(s, info, 20),
    landed: items.filter(i => i.state === 'landed').length,
    next: items.filter(i => i.state === 'queued' && i.kind !== 'job').length,
    done: items.filter(i => i.state === 'done' && (s.queue.night == null || i.night === s.queue.night)).length,
    failed,
    questions,
  }
}

let polling = false
/** How many queued tickets to list (`/board <n>`), and how many landed ones (`/board -<n>`): one of them is 0. */
let count = 5
let back = 0
/** Titles, tiers and repos of open tickets, read on `/board` and Refresh (the queue lacks them before a start). */
let info = new Map<string, Info>()

/** Reads the open tickets for what the queue does not say about them; a failed read keeps the last. */
async function learn($: EngineInterface): Promise<void> {
  try {
    const r = await $.http.fetch(`${HUB}/api/tickets`)
    if (!r.ok) return
    const rows = JSON.parse(r.text) as TicketRow[]
    info = new Map(rows.map(t => [`${t.map}#${String(t.num)}`, { title: t.title ?? '', tier: t.tier ?? '', repo: t.repo ?? '' }]))
  } catch {
    // titles fall back to keys
  }
}

/** The board as a few short lines for the transcript: the counts, then what runs, asks and failed. */
export function digest(b: Board): string {
  if (b.error !== '' && b.at === 0) return b.error
  const cut = (s: string): string => (s.length > 70 ? `${s.slice(0, 69)}…` : s)
  const lines = [
    `${b.paused ? 'Paused' : 'Running'} · ${String(b.running.length)} at work · ${String(b.next)} next · ${String(b.done)} done${b.landed > 0 ? ` · ${String(b.landed)} wait for review` : ''}`,
    ...b.running.map(r => `▶ ${cut(r.title)} (${r.detail})`),
    ...b.upcoming.map(r => `→ ${r.detail} · ${cut(r.title)}`),
    ...b.history.map(r => `${r.detail} · ${cut(r.title)}`),
    ...b.questions.map(q => `? ${cut(q.text)} → default ${q.fallback} in ${mins(q.left)}`),
    ...b.failed.slice(0, 5).map(r => `✗ ${cut(r.title)}: ${cut(r.detail)}`),
  ]
  if (b.failed.length > 5) lines.push(`✗ and ${String(b.failed.length - 5)} more failed`)
  if (b.error !== '') lines.push(b.error)
  return lines.join('\n')
}

/** Reads the hub and stores the board; a failed read keeps the last board and says why. */
async function pull($: EngineInterface): Promise<void> {
  try {
    const r = await $.http.fetch(`${HUB}/api/state`)
    if (!r.ok) throw new Error(`the hub answered ${String(r.status)}`)
    const b = summarize(JSON.parse(r.text) as HubState, info, count, back)
    await update($, board, () => b)
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err)
    await update($, board, b => ({ ...b, error: `cannot reach the hub: ${why}` }))
  }
}

/**
 * Sends the pictures and clips of up to SEND_RUNS landed runs not sent yet, newest first, as file cards: the hub
 * names a run's pictures, and they sit in its run's `<num>-media` folder. Says how many runs it sent, and why the
 * first refused send failed (a run is marked sent only once the tool says it delivered).
 */
async function sendPictures($: EngineInterface): Promise<{ runs: number; problem: string }> {
  const b = await read($, board)
  const done = new Set(await read($, sent))
  let runs = 0
  let problem = ''
  for (const r of b.recent) {
    if (runs >= SEND_RUNS) break
    if (r.media === undefined || r.seen === undefined || done.has(r.seen)) continue
    const answer = await $.http.fetch(`${HUB}/api/run?key=${encodeURIComponent(r.key)}`).catch(() => null)
    const names = answer?.ok === true ? ((JSON.parse(answer.text) as { run?: { pictures?: string[] | null } }).run?.pictures ?? []) : []
    if (names.length === 0) {
      await update($, sent, list => [...list, r.seen ?? r.key].slice(-500))
      continue
    }
    // stills first: they open at once on a phone
    const files = [...names].sort((x, y) => Number(/\.(mp4|webm)$/i.test(x)) - Number(/\.(mp4|webm)$/i.test(y))).slice(0, SEND_FILES)
    const out = await $.tool.call({ tool: 'SendUserFile', files: files.map(n => `${r.media ?? ''}/${n}`), caption: `${r.detail} · ${r.title}`, status: 'normal', display: 'render' })
    const said = 'deny' in out && typeof out.deny === 'string' ? `refused: ${out.deny}` : 'isError' in out && out.isError === true ? `failed: ${String((out as { text?: unknown }).text ?? '')}` : ''
    if (said !== '') {
      problem ||= said.slice(0, 300)
      break
    }
    await update($, sent, list => [...list, r.seen ?? r.key].slice(-500))
    // what the tool answered, quoted while delivery to the phone is unproven
    problem ||= runs === 0 ? `the tool answered: ${String((out as { text?: unknown }).text ?? '').replace(/\s+/g, ' ').slice(0, 160)}` : ''
    runs += 1
  }
  return { runs, problem }
}

/** Sends one write to the hub (an answer, a Seen), then reads the board again. */
async function post($: EngineInterface, path: string, body: object): Promise<void> {
  const r = await $.http.fetch(`${HUB}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) $.ui.toast(`The hub refused it (${String(r.status)})`)
  await pull($)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'board', description: 'The sb hub board: what runs, the next n tickets (5) with start and model (-n: the last n landed), questions, failed runs' })
    return next(e)
  })

  on('command.run', { command: 'board' }, async ($, e) => {
    // `/board 10`: the next 10; `/board -10` (or `-` alone, 5): the last 10 that landed
    const arg = e.args.trim()
    const n = Number.parseInt(arg.replace(/^-/, ''), 10)
    const many = Number.isNaN(n) ? 5 : Math.min(50, Math.max(0, n))
    ;[count, back] = arg.startsWith('-') ? [0, many] : [many, 0]
    const opened = await $.ui.open({ id: PANE, title: 'Hub board' })
    await learn($)
    await pull($)
    if (!polling) {
      polling = true
      $.clock.every(EVERY_MS, () => pull($))
    }
    // The pane may open on another screen (the Mac's app while you read on the phone), so the night also goes in
    // the transcript as a few short lines: every surface shows those. About 100 tokens, read with the next prompt.
    const { runs: pics, problem } = await sendPictures($).catch((err: unknown) => ({ runs: 0, problem: err instanceof Error ? err.message : String(err) }))
    const text = digest(await read($, board)) + (pics > 0 ? `\n📎 pictures of ${String(pics)} landed run${pics === 1 ? '' : 's'} below` : '') + (problem !== '' ? `\n📎 ${pics > 0 ? '' : 'pictures not sent: '}${problem}` : '')
    return { text: text + (opened.isPlaced ? '' : `\n(pane not shown: ${opened.reason})`) }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const b = await read($, board)
    const ago = b.at === 0 ? 'not read yet' : `read ${new Date(b.at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="column">
          <Text bold>
            {b.paused ? 'Paused' : 'Running'} · {b.running.length} at work · {b.next} next · {b.done} done{b.landed > 0 ? ` · ${b.landed} wait for review` : ''}
          </Text>
          <Text dimColor>{ago}</Text>
          {b.error !== '' && <Text color="red">{b.error}</Text>}
        </Box>

        {b.questions.length > 0 && (
          <Box flexDirection="column">
            <Text bold>Questions ({b.questions.length})</Text>
            {b.questions.map(q => (
              <Box key={q.id} flexDirection="column">
                <Text>{q.text}</Text>
                <Text dimColor>default in {mins(q.left)}: {q.fallback}</Text>
                <Box flexDirection="row" flexWrap="wrap" gap={1}>
                  {q.options.map(o => (
                    <Button key={`${q.id}:${o}`} label={o} variant={o === q.fallback ? 'primary' : 'secondary'} onPress={() => post($, '/api/answer', { qid: q.id, answer: o, by: 'you' })} />
                  ))}
                </Box>
              </Box>
            ))}
          </Box>
        )}

        <Box flexDirection="column">
          <Text bold>At work</Text>
          {b.running.length === 0 && <Text dimColor>Nothing runs.</Text>}
          {b.running.map(r => (
            <Text key={r.key}>
              {r.title} <Text dimColor>{r.detail}</Text>
            </Text>
          ))}
        </Box>

        {b.upcoming.length > 0 && (
          <Box flexDirection="column">
            <Text bold>Next {b.upcoming.length} of {b.next}</Text>
            {b.upcoming.map(r => (
              <Text key={r.key}>
                <Text dimColor>{r.detail}</Text> {r.title}
              </Text>
            ))}
          </Box>
        )}

        {b.history.length > 0 && (
          <Box flexDirection="column">
            <Text bold>Landed, newest first</Text>
            {b.history.map(r => (
              <Text key={r.key}>
                <Text dimColor>{r.detail}</Text> {r.title}
              </Text>
            ))}
          </Box>
        )}

        {b.failed.length > 0 && (
          <Box flexDirection="column">
            <Text bold>Failed, not looked at ({b.failed.length})</Text>
            {b.failed.slice(0, 10).map(r => (
              <Box key={r.key} flexDirection="column">
                <Text>{r.title}</Text>
                <Text color="red">{r.detail}</Text>
                <Button key={`seen:${r.seen ?? r.key}`} label="Seen" dimColor onPress={() => post($, '/api/run/seen', { key: r.seen })} />
              </Box>
            ))}
          </Box>
        )}

        <Button key="refresh" label="Refresh" dimColor onPress={async () => { await learn($); await pull($) }} />
      </Box>
    )
  })
}
