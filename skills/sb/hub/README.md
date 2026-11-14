# sb hub (typed workspace)

pnpm workspace for the TypeScript hub. Packages:

- `packages/contract`: zod schemas and types for every route sbhub.py serves (`ROUTES`, `answerSchema`, `routeOf`); `fixtures/` holds the hub's real answers, rewritten by `python3 -m unittest tests.test_contract_fixtures` (from `tests/`) and parsed by its Vitest test
  `RunTicketResult`, `RunTicketDetached` and `RunTicketStatus` type what `sbhub.py run-ticket <map>#<num>` prints (one ticket run to its end; `--detach`; `--status <pid>`); `fixtures/run-ticket/` is rewritten by `tests/test_run_ticket.py`
- `packages/server`: the hub's server (Hono on Node 24). It listens on 127.0.0.1:8765 (`SB_HUB_PORT` or `--port`), and on one extra address only when `SB_HUB_PHONE_ADDRESS` (the Mac's home Wi-Fi IPv4 address) and `SB_HUB_PHONE_SECRET` (16+ characters) are set: that address is then also a name the hub accepts, but a request to it gets an empty 404 until the phone opens `http://<address>:8765/?token=<secret>` once, which sets a cookie (hash of the secret, HttpOnly, SameSite=Strict, one year); every other name is refused, serves the built board at `/next/` (`/` opens it) and the Python hub's own board at `/classic`, and starts `sbhub.py serve` as its child on a port the OS picks. Every `/api` route is forwarded to that child, `links` (obsidian:// links by vault name and path in it, `obsidian://open?vault=<folder name>&file=<path>`, so a phone whose vault has that name opens them, for the ticket note, map, run board, report and log, only where the note exists; `SB_VAULT` names the vault) are added to every ticket row and queue item, and the answer is checked against the contract: a mismatch is logged on stderr and the caller gets a 502 instead. SIGTERM stops both; a child left by a server killed with SIGKILL is killed by the next one (its workers live on, as with `--take-over`)
- `packages/web`: Vite + React 19 board (React compiler on every file, Tailwind v4, shadcn); History (view 5) reads `GET /api/runs` (queue items plus the vault's run folders, by `skills/sb/scripts/sbruns.py`) and `GET /api/run?key=` for one run's checks, report and log

pnpm is pinned to 10.20.0 through `packageManager`. Run from the repo root or from this folder:

```sh
pnpm --dir skills/sb/hub install --frozen-lockfile
pnpm --dir skills/sb/hub typecheck   # tsc, strict + noUncheckedIndexedAccess + exactOptionalPropertyTypes
pnpm --dir skills/sb/hub lint        # ESLint flat config: strictTypeChecked, stylisticTypeChecked, react-hooks compiler rules
pnpm --dir skills/sb/hub test        # Vitest in every package
pnpm --dir skills/sb/hub build       # tsc for contract and server, vite build for web
pnpm --dir skills/sb/hub start       # the hub: node runs packages/server/src/index.ts as it is (type stripping)
```

As a service: `skills/sb/scripts/sbhub_service.sh install --ts` (installs the packages, builds, writes the LaunchAgent);
`sbhub_service.sh plist --ts` prints that LaunchAgent without installing it. Every Python suite that starts a hub
runs against this server with `SB_HUB_SERVER=ts`, for example (from `tests/`)
`SB_HUB_SERVER=ts python3 -m unittest test_hub_cli test_hub_hook test_hub_mcp test_hub_lan test_hub_queue`.

If `pnpm` fails with a corepack "Cannot find module" error, run `corepack prepare pnpm@10.20.0 --activate`.
Board dev server: `pnpm --dir skills/sb/hub/packages/web dev`.
