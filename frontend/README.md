# `frontend/` — Web application

**Purpose:** the user interface caregivers use. React + TypeScript, built with Vite.

- **Stack:** React 19, TypeScript, Vite 8, React Router, Tailwind CSS v4.
- **Contains:** pages (Dashboard, Residents list/detail, Alerts, Login), one typed
  API client in `src/api/`, shared UI components in `src/components/`, and `vitest`
  tests beside the code they test.
- **Must NOT contain:** business logic, ML code, database access, or hard-coded URLs
  (use `VITE_API_BASE_URL`, which defaults to `http://localhost:8000`).

## Status

Built and verified as far as it can be without a running backend:

| Check | Command | Result |
|---|---|---|
| Types compile | `npx tsc -b` | exit 0 |
| Production build | `npm run build` | exit 0 — 43 modules, ~313 kB JS (gzip ~94 kB), 24 kB CSS |
| Tests | `npm test` | 43 passed in 3 files |

**Not yet verified:** the app has never been run with `npm run dev` against a live
backend. "Shows live data fetched from the running backend" is therefore *not* claimed.

## Running it

```bash
npm install          # once
npm run dev          # dev server on http://localhost:5173
```

The API base URL:

```bash
# frontend/.env.local  (optional — the default already points at the local backend)
VITE_API_BASE_URL=http://localhost:8000
```

The backend must be running separately; see [`../README.md`](../README.md).

## Commands

```bash
npm run dev        # dev server on http://localhost:5173
npm run build      # types + production build into dist/
npm run preview    # serve the built output
npm run lint       # tsc --noEmit (type check only)
npm test           # vitest run
npm run test:watch # vitest in watch mode
```

## Layout

```
src/
  main.tsx            React entry point (mounts App)
  App.tsx             providers + routes
  index.css           Tailwind v4 theme + shared component classes
  api/                typed API client, errors, token storage
  auth/               AuthContext (session state, sign in/out)
  components/         AppLayout, RequireAuth, States, format helpers
  pages/              one file per page; tabs/ for the resident detail tabs
```

## Notes for whoever works on this next

- **Tailwind v4 is configured in CSS**, not in a `tailwind.config.js`. The theme
  tokens live in the `@theme` block in `src/index.css`.
- `@apply` only accepts **utilities**, so shared building blocks such as `btn` are
  declared with `@utility btn { ... }` — a plain `.btn` component class cannot be
  `@apply`-ed from another rule.
- The access token is kept in `localStorage`. That survives a page reload but is
  readable by JavaScript, so it is not proof against XSS. Documented trade-off;
  a production system would prefer an httpOnly cookie.
