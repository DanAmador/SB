// Every word the map shows, in each language it speaks.
// A new language is one more table here and one more value of `language` in plugin.json.
import type { StationId } from './types.ts'

export type Strings = {
  title: string
  command: string
  opened: string
  cannotOpen: (reason: string) => string
  /** The pane's buttons in an editor, where the pane cannot be made taller. */
  zoomOut: string
  zoomIn: string
  hideMap: string
  showMap: string
  stations: Record<StationId, string>
  newMessage: string
  answerReady: string
  turnAborted: string
  step: (n: number) => string
  subagent: string
  compacting: string
  addedContext: (when: string) => string
  addedMemory: (when: string) => string
  toMessage: string
  atStart: string
  records: (n: number, shown: string) => string
  stopped: (tool: string) => string
  askedPermission: (tool: string) => string
  checkBefore: (tool: string) => string
  running: string
  nothingYet: string
  noCounts: string
  idle: string
  context: string
  andMore: (n: number) => string
  webSearch: string
  artifact: string
  workflow: string
  skill: string
  loadingTools: string
  questionForYou: string
  fileForYou: string
  ms: (n: number) => string
  seconds: (s: string) => string
  minutes: (m: number, s: number) => string
}

const en: Strings = {
  title: 'Work map',
  command: 'Open the work map beside the chat',
  opened: 'Work map opened.',
  cannotOpen: reason => `Nowhere to show the map right now: ${reason}`,
  zoomOut: 'Zoom out',
  zoomIn: 'Zoom in',
  hideMap: 'Hide map',
  showMap: 'Show map',
  stations: {
    you: 'You',
    model: 'Model',
    memory: 'Memory',
    files: 'Files',
    shell: 'Shell',
    web: 'Network',
    browser: 'Browser',
    agents: 'Agents',
    skills: 'Skills',
    hooks: 'Hooks',
  },
  newMessage: 'new message',
  answerReady: 'answer ready',
  turnAborted: 'turn interrupted',
  step: n => `step ${n}`,
  subagent: 'subagent',
  compacting: 'compacting context',
  addedContext: when => `added context ${when}`,
  addedMemory: when => `added memory ${when}`,
  toMessage: 'to the message',
  atStart: 'at session start',
  records: (n, shown) => `${n} record${n === 1 ? '' : 's'}: ${shown}`,
  stopped: tool => `stopped ${tool}`,
  askedPermission: tool => `asked permission: ${tool}`,
  checkBefore: tool => `check before ${tool}`,
  running: 'running',
  nothingYet: 'Nothing yet.',
  noCounts: 'No counts yet.',
  idle: 'Nothing is running.',
  context: 'context',
  andMore: n => ` and ${n} more`,
  webSearch: 'web search',
  artifact: 'artifact',
  workflow: 'workflow',
  skill: 'skill',
  loadingTools: 'loading tools',
  questionForYou: 'question for you',
  fileForYou: 'file for you',
  ms: n => `${n} ms`,
  seconds: s => `${s} s`,
  minutes: (m, s) => `${m} min ${s} s`,
}

// lot-map's other languages are left out: the hub speaks English.
const TABLES = new Map<unknown, Strings>([['en', en]])

export const stringsFor = (language: unknown): Strings => TABLES.get(language) ?? en
