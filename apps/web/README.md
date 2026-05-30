# apps/web — Divine Ruin marketing site

The SEO-strong, fast landing + waitlist page for Divine Ruin (the audio-first AI
tabletop RPG). Standalone **Bun-native** app: `Bun.serve` for the server, Bun's
bundler for the build, React for the UI. Bun has no built-in SSR/SSG, so the
build does a **build-time prerender** (static-site generation) for SEO and Core
Web Vitals — the served HTML carries real content, then the client hydrates it.

Plain CSS + CSS custom properties (zero UI-framework deps). Design tokens flow in
from `@divineruin/design-tokens` (shared with mobile); the waitlist write lives on
`apps/server` (`POST /api/waitlist`) so this app stays static-deployable.

## Commands

Run from `apps/web/` with Bun (never npm/node):

| Command | What it does |
| --- | --- |
| `bun run dev` | `bun --hot src/server.ts` — HMR dev server on `:8083`. Generates a dev-only index that links `fonts.css` so Bun bundles + inlines the woff2 on the fly (no CWV budget in dev). |
| `bun run build` | `bun run scripts/prerender.ts` — the SSG step (below). Writes `dist/`. |
| `bun run start` | `NODE_ENV=production bun src/server.ts` — serves the prebuilt `dist/` on `PORT` (default `8083`). Throws an actionable error if `dist/index.html` is missing, so run `build` first. |
| `bun run typecheck` | `tsc --noEmit`. |
| `bun test` | unit tests (`bun:test`). |

Production serve is `build` then `start`. The e2e harness builds + serves on `:8085`.

## Build / SSG (`scripts/prerender.ts`)

1. `Bun.build` bundles `index.html` → content-hashed JS/CSS chunks in `dist/`
   (stable `index.html` entry, immutable hashed assets). `env: "PUBLIC_*"` inlines
   the `PUBLIC_`-prefixed deploy env into the client bundle (see below).
2. `renderAppHTML()` (`src/entry-server.tsx`) renders the App to a string, spliced
   into the empty `<div id="root">` so the served HTML is SEO-visible and the
   client can hydrate it.
3. The `<head>` gets the LCP **font preloads first** (so the preload scanner finds
   them early), then the SEO meta / OG / JSON-LD block (`src/lib/seo.ts`
   `buildMetaTags`).
4. Fonts (`src/fonts/`), the audio sample (`src/audio/`), and the OG image +
   favicon (`public/`) are copied **verbatim** into `dist/` — bypassing the
   bundler so the woff2 stay separately cacheable and the audio/image keep stable
   URLs. (The `og-image.svg` source is not shipped; only the rasterized `.png`.)
5. `robots.txt` + `sitemap.xml` are **generated per build** from
   `PUBLIC_SITE_ORIGIN` (`src/lib/crawl.ts`) so they track the deploy origin.

The capstone gate `e2e/specs/web-production.e2e.ts` proves a served prod build
scores Lighthouse Performance/SEO/Accessibility ≥90 with green CWV and serves the
meta/sitemap/robots.

## Serving & cache strategy (`src/server.ts`, `src/cache-policy.ts`)

The prod server precomputes, at startup, each `dist/` file's bytes + a
content-hash **ETag** + its **Cache-Control**, then serves with ETag/304
revalidation. Two cache classes (`cacheControlFor`):

- **`public, max-age=31536000, immutable`** — content-hashed JS/CSS chunks **and**
  the woff2 fonts (their names are content-stable; re-subsetting is a deliberate
  deploy event, and they're bandwidth-heavy + fetched every load).
- **`no-cache`** (ETag/304 revalidate) — stable names that can change in place:
  `index.html`, `fonts/fonts.css`, `robots.txt`, `sitemap.xml`, `favicon.ico`,
  `og-image.png`, and everything under `audio/` (lazy `preload="none"`, so
  revalidating costs nothing at page load).

## Deploy env gates

Set these **in the build environment** so they bake/inline at build time. All are
optional with safe fallbacks, but production must set them:

| Var | Set to (prod) | Effect | Unset fallback |
| --- | --- | --- | --- |
| `PUBLIC_API_URL` | `https://divineruin.app` | **Inlined into the client bundle** — the waitlist `POST` target (`src/lib/api.ts`). | `http://localhost:3001` |
| `PUBLIC_SITE_ORIGIN` | `https://divineruin.app` | **Build-time only** (read in `prerender.ts`, not in the client bundle) — bakes canonical / `og:url` / JSON-LD and generates robots/sitemap. | `https://divineruin.com` |
| `PUBLIC_ANALYTICS_URL` | first-party beacon endpoint | **Inlined into the client bundle** — when set, `navigator.sendBeacon` mirrors each in-page `dr:analytics` event to it (`src/lib/analytics.ts`). No third-party scripts, cookies, or PII. | unset = in-page CustomEvent only, no beacon |

`PUBLIC_API_URL` / `PUBLIC_ANALYTICS_URL` are client-side, so they're inlined by
`Bun.build`'s `env: "PUBLIC_*"`; `PUBLIC_SITE_ORIGIN` is consumed at build time and
never enters the bundle.

## Deploy path

`bun run build` produces a fully static `dist/`. Deploy it either by:

- running the bundled Bun prod server (`bun run start`, serves `dist/` with the
  ETag/cache policy above), or
- uploading `dist/` to any static host/CDN.

Either way, set the three `PUBLIC_*` vars in the build environment (not at
runtime) so the canonical origin, crawl assets, and client API/analytics targets
are correct in the shipped artifact.
