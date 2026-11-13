# sb hub (typed workspace)

pnpm workspace for the TypeScript hub. Packages:

- `packages/contract`: shared API types (placeholder until the real contract lands)
- `packages/server`: the TypeScript server that will front the Python hub
- `packages/web`: Vite + React 19 board (React compiler on every file, Tailwind v4, shadcn)

pnpm is pinned to 10.20.0 through `packageManager`. Run from the repo root or from this folder:

```sh
pnpm --dir skills/sb/hub install --frozen-lockfile
pnpm --dir skills/sb/hub typecheck   # tsc, strict + noUncheckedIndexedAccess + exactOptionalPropertyTypes
pnpm --dir skills/sb/hub lint        # ESLint flat config: strictTypeChecked, stylisticTypeChecked, react-hooks compiler rules
pnpm --dir skills/sb/hub test        # Vitest in every package
pnpm --dir skills/sb/hub build       # tsc for contract and server, vite build for web
```

If `pnpm` fails with a corepack "Cannot find module" error, run `corepack prepare pnpm@10.20.0 --activate`.
Board dev server: `pnpm --dir skills/sb/hub/packages/web dev`.
