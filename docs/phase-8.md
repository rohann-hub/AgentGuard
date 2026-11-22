# Phase 8: Admin dashboard

A web console for the people who run AgentGuard. It approves or rejects held requests,
registers and revokes agents, shows what the firewall caught, and reads and verifies the
audit log. It uses the same admin APIs as anything else, so it adds no new powers.

Stack: React 19, TypeScript, Tailwind CSS 4, built with Vite. The backend serves the built
files at `/dashboard/`; there is no second service to run.

## What was built

| File | Role |
|---|---|
| `dashboard/` | The React app (`src/views/` has one file per screen) |
| `dashboard/src/api.ts` | Typed client for the admin APIs; holds the admin key in a closure only |
| `backend/app/api/dashboard.py` | Serves `dashboard/dist` at `/dashboard/` with strict security headers |
| `backend/app/api/routes/overview.py` | `GET /api/v1/overview`: tools, live policy version, counts |
| `backend/app/api/routes/audit.py` | Audit list gains `agent_name`, `decision` and `event_type` filters |
| `Dockerfile` | A Node build stage; the final image has only the static files, no Node |
| `.github/workflows/tests.yml` | New `dashboard` job: type check, tests, build |

## Screens

| Screen | What you can do |
|---|---|
| Overview | Allowed, denied and held counts; agents; the audit chain check; registered tools and the policy version OPA has loaded now (or a warning that OPA is down) |
| Approvals | Requests policy held for a person, with the redacted arguments and reason. **Approve request** or **Reject**. Filter by state |
| Agents | List agents, register one (its key is shown once, with a copy button), revoke one (asks to confirm first) |
| Security | Denied calls and firewall findings from the latest 1,000 events, with a count per entity type |
| Audit log | Filter by agent, decision, event type or request id; open a row for its fingerprints and hashes |

## How to use it

With Docker, it is already in the image:

```bash
docker compose up -d --build --wait
open http://localhost:8000/dashboard/
```

Sign in with the admin key whose SHA-256 is in `AGENTGUARD_ADMIN_API_KEY_HASH`.

Without Docker, build it once and point the backend at it:

```bash
cd dashboard && npm ci && npm run build
AGENTGUARD_DASHBOARD_DIR=$PWD/dist uvicorn app.main:app   # from backend/
```

For working on the UI, `npm run dev` serves it on http://localhost:5173/dashboard/ and proxies
`/api` to a backend on port 8000.

### New and changed APIs

- `GET /api/v1/overview` (admin key) returns `policy_version` (read live from OPA, `null` if
  OPA does not answer), `tools` (name, action, and whether facts are verified before policy),
  and counts of `agents` by status, `approvals` by state and `decisions` by policy decision.
- `GET /api/v1/audit` also takes `agent_name`, `decision` and `event_type`.

## Security choices

- **The admin key lives in memory only.** It is kept in React state and a closure in
  `api.ts`: never in `localStorage`, `sessionStorage`, cookies or the URL. Reloading or
  closing the tab signs you out. A key the server refuses signs you out at once.
- **No new powers.** Every action calls the existing admin APIs with `X-Admin-Key`. Approving
  still binds to the exact request hash, is single use, expires, and policy runs again when
  the agent resubmits.
- **Strict headers** on every dashboard file: a Content-Security-Policy that allows only the
  dashboard's own scripts, styles, fonts and API (`default-src 'self'`, no inline scripts),
  `frame-ancestors 'none'` and `X-Frame-Options: DENY` against clickjacking,
  `Referrer-Policy: no-referrer` and `nosniff`. `index.html` is `no-cache`; assets are
  content-hashed.
- **No sensitive data shown.** The audit log stores fingerprints, not arguments or responses,
  and findings carry entity types and paths, never values. Approvals show arguments after the
  firewall redacted them.
- **Policy is read-only here.** Rego changes still go through files, `opa test` and a PR.
- Fonts are bundled (IBM Plex), so the page makes no third-party requests.

## Design

Built with the taste-skill guidelines, adapted to an admin tool: warm neutral grounds and one
near-black ink, colour only for state (allowed, denied, waiting), one teal accent for focus and
links, sharp 4/6/8 radii, IBM Plex Sans with Plex Mono for ids and hashes, 44px controls,
buttons that step up on hover and sink on press, no scroll animations. Light and dark follow
the system setting. Every control has a visible label or an accessible name, focus rings show
at once, and it works at phone width with no sideways scroll.

## Tests

| Where | What |
|---|---|
| `backend/tests/unit/test_overview.py` | Admin key required; counts, tools and policy version; renders when OPA is down; audit filters |
| `backend/tests/unit/test_dashboard.py` | Served with the security headers; no path traversal; off unless configured; fails fast on a bad folder |
| `backend/tests/integration/test_stack.py` | The image serves the built dashboard; overview reads the live policy version |
| `dashboard/src/api.test.ts` | Key sent only as a header, never in the URL; no cookies; ids escaped; errors surfaced |
| `dashboard/src/lib.test.ts` | Which events count as security events; finding counts; time formatting |

Checked by hand in Chromium at 1440 and 390 wide, light and dark: sign in (wrong key refused),
approve a held refund, register an agent and copy its key, revoke it (its key then gets 401 at
the proxy), audit filters, and that the key is in no browser storage and is forgotten on reload.

## Known limitations

- **One shared admin key.** There are no named users, so the audit log cannot say which
  person approved a request. Named approvers and proper sign-in belong in Phase 10.
- **Security view scans the latest 1,000 events** in the browser. Older events are still in
  the audit log; a server-side filter will be needed as volume grows.
- **The audit log shows the latest 200 matching events**, with no paging yet.
- **No live updates.** Use Refresh; nothing polls in the background.
- **Counts on the overview** are computed on each request; fine at this scale, worth caching
  later.
