import { expect, test } from 'claude-code/testing'

import { hm } from '../hooks/register'

const PANE = {
  plugin: 'hub-board',
  component: 'Pane',
  requestId: 'hub-board',
  props: {
    title: 'Hub board',
    isFocused: false,
    bodyColumns: 40,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const NOW = 1_000_000
const STATE = {
  now: NOW,
  seen: ['m/a#4@' + String(NOW - 50)],
  questions: {
    q1: { q: 'Where do the sounds come from?', options: ['Made by code', 'A sound pack'], default: 'Made by code', deadline: NOW + 600, answer: null },
    q2: { q: 'Already answered', options: ['x', 'y'], default: 'x', deadline: NOW + 60, answer: 'x' },
  },
  queue: {
    paused: false,
    night: 'n1',
    agents: ['personal'],
    items: [
      { key: 'm/a#1', kind: 'ticket', state: 'running', title: 'Blast knife explodes once', model: 'sonnet', started: NOW - 600, night: 'n1', repo: '/r' },
      { key: 'm/a#2', kind: 'ticket', state: 'queued', night: 'n1' },
      { key: 'm/a#8', kind: 'ticket', state: 'queued', night: 'n1' },
      { key: 'job:x', kind: 'job', state: 'queued', title: 'close-off' },
      { key: 'm/a#3', kind: 'ticket', state: 'failed', title: 'Ropes hold', note: 'no commit after abc\nmore', ended: NOW - 100, night: 'n1' },
      { key: 'm/a#4', kind: 'ticket', state: 'failed', title: 'Already seen', note: 'x', ended: NOW - 50, night: 'n1' },
      { key: 'm/a#5', kind: 'ticket', state: 'skipped', title: 'Merged away', note: 'no longer open: dropped: merged into 9', ended: NOW - 40, night: 'n1' },
      { key: 'm/a#6', kind: 'ticket', state: 'done', title: 'Done tonight', started: NOW - 1230, ended: NOW - 30, night: 'n1' },
      { key: 'm/a#7', kind: 'ticket', state: 'landed', title: 'Waits for review', model: 'opus', started: NOW - 900, spend: { run_minutes: 14 }, night: 'n1' },
    ],
    cleared: [
      { key: 'm/a#0', kind: 'ticket', state: 'done', title: 'Landed yesterday', model: 'sonnet', started: NOW - 90000, ended: NOW - 89000, verdict: 'partly' },
      { key: 'job:c', kind: 'job', state: 'done', title: 'close-off', started: NOW - 5000, ended: NOW - 4000 },
    ],
  },
}

test('the board shows the night on the phone, and a press answers a question', async ($, on) => {
  const posts: { url: string; body: string }[] = []
  // the queue carries no title or model for a ticket not started: the ticket list does
  const TICKETS = [
    { map: 'm/a', num: 2, title: 'Next one', tier: 'opus', repo: '/r' },
    { map: 'm/a', num: 8, title: 'Then this', tier: 'sonnet', repo: '/r' },
  ]
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('http.fetch', (_, e) => {
    if (e.init?.method === 'POST') posts.push({ url: e.url, body: typeof e.init.body === 'string' ? e.init.body : '' })
    const text = e.init?.method === 'POST' ? '{"ok":true}' : e.url.endsWith('/api/tickets') ? JSON.stringify(TICKETS) : JSON.stringify(STATE)
    return { value: { status: 200, ok: true, headers: {}, text } }
  })

  await $.session.start({ cwd: '/', surface: 'mobile', isInteractive: true })
  const said = await $.command.run({ command: 'board', args: '1' } as Parameters<typeof $.command.run>[0])
  // the transcript gets the night too, for a screen that does not show the pane (the phone)
  expect(said.text).toContain('Running · 1 at work · 2 next · 1 done · 1 wait for review')
  // tonight's runs take 20 min: the running one ends in 10, then one account runs the repo's next ticket
  expect(said.text).toContain(`▶ Blast knife explodes once (sonnet · 10 min · ends ~${hm(NOW + 600)})`)
  expect(said.text).toContain(`→ ~${hm(NOW + 600)} opus · Next one`)
  // /board 1 lists one
  expect(said.text).not.toContain('Then this')
  expect(said.text).toContain('? Where do the sounds come from?')
  expect(said.text).toContain('✗ Ropes hold: no commit after abc')

  const ui = await $.ui.mount({ ...PANE, surface: 'mobile' })
  expect((await ui.find({ type: 'Text', text: /1 at work · 2 next · 1 done · 1 wait for review/ }))?.text).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Blast knife explodes once/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Where do the sounds come from/ })).toBeDefined()
  // an answered question, a run already seen and a run skipped for a closed ticket are left out
  expect(await ui.find({ type: 'Text', text: /Already answered/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /Already seen/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /Merged away/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /Failed, not looked at \(1\)/ })).toBeDefined()

  await ui.press({ key: 'q1:A sound pack' })
  expect(posts.at(-1)).toEqual({ url: 'http://127.0.0.1:8765/api/answer', body: JSON.stringify({ qid: 'q1', answer: 'A sound pack', by: 'you' }) })
  await ui.press({ key: 'seen:m/a#3@' + String(NOW - 100) })
  expect(posts.at(-1)?.body).toBe(JSON.stringify({ key: 'm/a#3@' + String(NOW - 100) }))

  // with no number it lists 5; the second ticket starts once the first is done (one repo, one at a time)
  const all = await $.command.run({ command: 'board', args: '' } as Parameters<typeof $.command.run>[0])
  expect(all.text).toContain(`→ ~${hm(NOW + 1800)} sonnet · Then this`)

  // with a minus: the last ones that landed, newest first, cleared ones too, never a job; no next list
  const back = await $.command.run({ command: 'board', args: '-5' } as Parameters<typeof $.command.run>[0])
  const lines = (back.text ?? '').split('\n')
  expect(lines.filter(l => / · (Waits for review|Done tonight|Landed yesterday)/.test(l))).toEqual([
    `✓ ${hm(NOW - 30)} 20m · Done tonight`,
    `◐ ${hm(NOW - 60)} opus 14m · Waits for review`,
    `✓ ${hm(NOW - 89000)} sonnet 17m partly · Landed yesterday`,
  ])
  expect(back.text).not.toContain('close-off')
  expect(lines.some(l => l.startsWith('→'))).toBe(false)
  await ui.unmount()
})

test('a hub that cannot be reached says so', async ($, on) => {
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('http.fetch', () => {
    throw new Error('connection refused')
  })
  await $.session.start({ cwd: '/', surface: 'mobile', isInteractive: true })
  await $.command.run({ command: 'board', args: '' } as Parameters<typeof $.command.run>[0])
  const ui = await $.ui.mount({ ...PANE, surface: 'mobile' })
  expect(await ui.find({ type: 'Text', text: /cannot reach the hub/ })).toBeDefined()
  await ui.unmount()
})

test('each /board sends the pictures of landed runs not sent yet, stills first, once', async ($, on) => {
  const sends: { files: string[]; caption?: string }[] = []
  const state = {
    now: NOW,
    queue: {
      items: [
        { key: 'm/a#7', kind: 'ticket', state: 'landed', title: 'Arms', model: 'opus', started: NOW - 900, run: '/runs/tonight' },
        { key: 'm/a#9', kind: 'ticket', state: 'done', title: 'No pictures', started: NOW - 2000, ended: NOW - 1500, run: '/runs/tonight' },
      ],
    },
  }
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('http.fetch', (_, e) => {
    const text = e.url.includes('/api/run?key=m%2Fa%237')
      ? JSON.stringify({ run: { pictures: ['idle.mp4', 'still.png'] } })
      : e.url.includes('/api/run?') ? JSON.stringify({ run: { pictures: [] } })
      : e.url.endsWith('/api/tickets') ? '[]' : JSON.stringify(state)
    return { value: { status: 200, ok: true, headers: {}, text } }
  })
  on('tool.call', (_, e) => {
    if (e.tool === 'SendUserFile') sends.push({ files: [...(e as unknown as { files: string[] }).files], caption: (e as unknown as { caption?: string }).caption })
    return { result: {} }
  })
  await $.session.start({ cwd: '/', surface: 'mobile', isInteractive: true })
  const first = await $.command.run({ command: 'board', args: '' } as Parameters<typeof $.command.run>[0])
  expect(sends).toHaveLength(1)
  expect(sends[0]?.files).toEqual(['/runs/tonight/7-media/still.png', '/runs/tonight/7-media/idle.mp4'])
  expect(sends[0]?.caption).toContain('Arms')
  expect(first.text).toContain('📎 pictures of 1 landed run below')
  const again = await $.command.run({ command: 'board', args: '' } as Parameters<typeof $.command.run>[0])
  expect(sends).toHaveLength(1)
  expect(again.text).not.toContain('📎')
})
