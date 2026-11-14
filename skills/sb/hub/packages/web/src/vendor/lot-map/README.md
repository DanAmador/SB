# lot-map (vendored)

Drawing and classifying code from **lot-map** by Aleksei Volodin, <https://github.com/alexeyw/lot-map>, MIT licence
(see `LICENSE` here).

Copied from `hooks/` at the repository's HEAD on 2026-11-14: `classify.ts`, `draw.ts`, `palette.ts`, `setup.ts`,
`text.ts`, and the types of `types/index.d.ts` (`types.ts`). Changes: imports name their `.ts` ending and point at
`./types.ts`; `text.ts` keeps the English table only; `types.ts` drops the editor-plugin module declaration.
Nothing else is edited, so a newer lot-map can be dropped over it.
