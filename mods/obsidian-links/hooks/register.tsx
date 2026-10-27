import type { Register } from 'claude-code'

// The vault sbmap reads: $SB_VAULT, else ~/Documents/Second Brain. Set at session start.
let VAULT: string | null = null

// A markdown link's target: `](obsidian://…)` or `](file:///…)`.
const LINK = /\]\(((?:obsidian|file):\/\/[^)\s]+)\)/g

const decode = (s: string): string => {
  try {
    return decodeURIComponent(s)
  } catch {
    return s
  }
}

// The vault file a link points at, or null for any other link.
const vaultPath = (href: string): string | null => {
  let path: string | null = null
  if (href.startsWith('obsidian://open?')) {
    const match = /[?&]path=([^&]+)/.exec(href)
    path = match?.[1] !== undefined ? decode(match[1]) : null
  } else if (href.startsWith('file://')) {
    path = decode(href.slice('file://'.length))
  }

  return path !== null && VAULT !== null && path.startsWith(VAULT) ? path : null
}

const fileHref = (path: string): string =>
  'file://' + path.split('/').map(encodeURIComponent).join('/')

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const vault = (await $.env.get('SB_VAULT')) ?? `${await $.env.get('HOME')}/Documents/Second Brain`
    VAULT = vault.endsWith('/') ? vault : vault + '/'
    return next(e)
  })

  on('ui.render', { component: 'AssistantMessage' }, ($, e, next) => {
    const hrefs: string[] = []
    // Markdown draws only https, http and file links, so an obsidian:// link is
    // redrawn as the file link it names; the click still goes to Obsidian.
    const text = e.props.text.replace(LINK, (whole, href: string) => {
      const path = vaultPath(href)
      if (path === null) {
        return whole
      }
      const drawn = fileHref(path)
      hrefs.push(drawn)

      return `](${drawn})`
    })

    if (hrefs.length === 0) {
      return next(e)
    }

    const { Markdown } = $.ui.resolve(e)

    return (
      <Markdown
        key="reply"
        text={text}
        pressableLinks={hrefs}
        onLinkPress={link => {
          const path = vaultPath(link.href)
          if (path !== null) {
            void $.process.run(['open', 'obsidian://open?path=' + encodeURIComponent(path)])
          }
        }}
      />
    )
  })
}
