# Researchdesk frontend

Next.js, React, and TypeScript frontend for the Researchdesk API. All displayed
research comes from the API; the application has no production seed data or
canned model responses.

Use Node 24 LTS (or a current supported Node 22/26 release). The current test
runner does not support the non-LTS Node 25 release.

```sh
npm ci
cp .env.example .env.local
npm run dev
```

Start the backend on `http://127.0.0.1:8010`, or set `RESEARCH_API_URL` in the
server environment. The browser calls the application's same-origin `/api`
proxy. The development and production scripts bind loopback by default.

Authentication uses the backend's HTTP-only session cookie. Open **Environment**
to sign in when operator authentication is enabled. No operator key is embedded
in the browser or automatically added by the proxy. Configure allowed origins
on both services when deploying behind a reverse proxy. A public read-only
deployment must enforce read-only operation in the API, not merely hide buttons.

```sh
npm run typecheck
npm test
npm run build
npm start
```

Tests cover API response validation, structured tool output, rejected reviews,
metric units, unavailable valuations, duplicate-submit prevention, read-only UI,
source-link handling, authentication forwarding, cross-origin rejection, and
bounded proxy bodies. Fixtures live only under `src/test/`; production views do
not import them.

The frontend polls durable case events using the server's sequence cursor and
refreshes resource snapshots. It distinguishes API connection failures from
empty results, keeps prior data explicitly marked when refresh fails, and
clears cached private views when the session changes. Missing market valuations
remain unavailable rather than displaying zero or an inferred account value.
