/** A run on the board: its key, its title and what to say beside it; `media`, a landed run's pictures folder. */
export type Row = { key: string; title: string; detail: string; seen?: string; media?: string }

/** An open question the hub holds, answered from the pane. */
export type Ask = { id: string; text: string; options: string[]; fallback: string; left: number }

/** What the pane shows: the hub's state cut down to what a phone reads. */
export type Board = {
  /** When it was read (seconds); 0 before the first read. */
  at: number
  /** Why the last read failed, or "" when it worked. */
  error: string
  paused: boolean
  running: Row[]
  /** The next tickets in queue order, each with its forecast start and model in `detail`. */
  upcoming: Row[]
  /** The last tickets that landed, newest first: `detail` is a mark (✓ judged, ◐ waits for review), time, model, minutes. */
  history: Row[]
  /** The last 20 that landed, for sending their pictures. */
  recent: Row[]
  landed: number
  next: number
  done: number
  failed: Row[]
  questions: Ask[]
}

declare module 'claude-code' {
  interface PluginState {
    'hub-board': { board: Shaped<Board>; sent: Shaped<string[]> }
  }
}
