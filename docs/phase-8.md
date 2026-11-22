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
| `dashboard/vercel.json` | Optional hosting on Vercel (see below) |

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
- Fonts are bundled, so the page makes no third-party requests.

## Design

The look follows the reference Soumik chose: an airy light ground with soft iridescent arcs
(pure CSS, no images), translucent white cards, and the **Vanilla `#FFEBAF`** and
**Moonstone `#4C9DB0`** palette. Headings are set in Instrument Serif, a high-contrast
display serif, with a moonstone second line under each title; data and controls use
Instrument Sans, and ids and hashes IBM Plex Mono. All fonts are bundled.

Moonstone is too light for small text on white (3.1:1), so text, links, focus rings and the
primary button use a deeper moonstone (`#2B6676`, 6:1), with vanilla text on that button
(5.4:1). Pure moonstone is kept for large type and decoration; vanilla marks things waiting
on a person. Body text is 7:1 or more and muted labels 4.5:1 or more.

Built with the taste-skill guidelines, adapted to an admin tool: one accent family, colour
only for state, sharp 4/6/8 radii, 44px controls, buttons that step up on hover and sink on
press, no scroll animations. Light and dark follow the system setting. Every control has a
visible label or an accessible name, focus rings show at once, and it works at phone width
with no sideways scroll.

## Tests

| Where | What |
|---|---|
| `backend/tests/unit/test_overview.py` | Admin key required; counts, tools and policy version; renders when OPA is down; audit filters |
| `backend/tests/unit/test_cors.py` | No cross-origin access by default; only listed origins; exact origins only |
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

## Deploy the dashboard on Vercel

The dashboard is a static site, so Vercel can host it. It only shows data when it can reach a
running AgentGuard backend, which must be hosted separately (Vercel does not run the
backend, PostgreSQL or OPA). The backend must be on **HTTPS**: a page on Vercel cannot call
an `http://` API.

`dashboard/vercel.json` sets the build (`DASHBOARD_BASE=/ npm run build`), the output folder
(`dist`), a rewrite to `index.html`, and the same security headers the backend sends
(`connect-src` allows `https:` so the page can reach your API).

### Steps

1. In Vercel: **Add New → Project**, import `rohann-hub/AgentGuard`.
2. **Root Directory:** `dashboard`. Vercel then reads `dashboard/vercel.json`; leave the
   framework, build and output settings as detected.
3. **Environment Variables:** add `VITE_API_BASE_URL` = your backend's public HTTPS address,
   with no trailing slash, e.g. `https://agentguard-api.example.com`.
4. **Deploy.** Note the address Vercel gives you, e.g. `https://agentguard-dashboard.vercel.app`.
5. On the backend, allow that exact address and restart it:

   ```bash
   AGENTGUARD_CORS_ORIGINS=["https://agentguard-dashboard.vercel.app"]
   ```

   Add each address that should work (a custom domain too). Wildcards are refused on
   purpose. Vercel preview deployments get their own addresses and will not reach the API
   unless you add them.
6. Open the Vercel address and sign in with the admin key.

If sign-in says "No AgentGuard API answered here", `VITE_API_BASE_URL` is missing (it is
read at build time, so redeploy after setting it). If it says "AgentGuard is not answering",
the backend is down, not on HTTPS, or the Vercel address is not in `AGENTGUARD_CORS_ORIGINS`.

### What changes on the backend

- `AGENTGUARD_CORS_ORIGINS` (JSON list, default `[]`): exact browser origins allowed to call
  the APIs. Only `GET` and `POST`, only the `X-Admin-Key`, `Content-Type` and `Accept`
  headers, never cookies. Empty means no cross-origin access, as before.
- The admin key still travels only as a header, now across origins, so serve the backend
  over HTTPS and keep the allow-list short.
