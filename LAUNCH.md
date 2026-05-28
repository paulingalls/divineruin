# Launch Checklist — divineruin.app (marketing site)

The pre-launch gate for the `apps/web` marketing site. Detail on each item lives
in [`apps/web/README.md`](apps/web/README.md); this is the short checklist to run
before shipping `divineruin.app`.

## Deploy env gates (set in the BUILD environment, before `bun run build`)

These bake/inline at build time — setting them at runtime is too late. All have
safe fallbacks, but production **must** set them:

- [ ] `PUBLIC_SITE_ORIGIN=https://divineruin.app` — bakes canonical / `og:url` /
      JSON-LD and generates `robots.txt` + `sitemap.xml` from this origin.
      (Build-time only; never enters the client bundle. Unset → `divineruin.com`.)
- [ ] `PUBLIC_API_URL=https://divineruin.app` — the waitlist `POST` target,
      inlined into the client bundle. (Unset → `http://localhost:3001`, which
      silently breaks the live waitlist.)
- [ ] `PUBLIC_ANALYTICS_URL=<first-party beacon endpoint>` — optional. When set,
      `navigator.sendBeacon` mirrors each in-page `dr:analytics` event to it (no
      third-party scripts, cookies, or PII). Unset → in-page CustomEvent only.

## Build & verify

- [ ] `cd apps/web && bun run build` — produces the static `dist/`.
- [ ] Capstone gate green: `cd e2e && npx playwright test specs/web-production.e2e.ts --project=web-lighthouse`
      — Lighthouse Performance/SEO/Accessibility ≥90, CWV green, meta/OG +
      `sitemap.xml` + `robots.txt` served.
- [ ] Spot-check the served `dist/index.html`: canonical/`og:url` point at
      `https://divineruin.app/`; `/sitemap.xml` and `/robots.txt` carry the same
      origin.

## Ship

- [ ] Deploy `dist/` — either run the bundled Bun prod server
      (`bun run start`, serves with the ETag + immutable/no-cache policy) or
      upload `dist/` to a static host/CDN.
- [ ] Confirm `apps/server` (`POST /api/waitlist`) is reachable at the
      `PUBLIC_API_URL` origin and accepting signups.

See `apps/web/README.md` for the SSG/prerender flow and the cache strategy.
