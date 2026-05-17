# Object Storage Migration — Spec

Status: **Proposal** (2026-05-17) — not yet decided. Source material for a future execution plan.

## Summary

Move all binary media assets (PNGs, MP3s, generated portraits) out of the git repo and into S3-compatible object storage. Local dev uses a containerized S3-compatible server (rustfs or MinIO); production uses DigitalOcean Spaces. The Bun server fetches/streams from the bucket via an S3 client; the Expo mobile app fetches dynamic content art (locations, marketing) from the same store at runtime with on-device caching, while keeping app-shell chrome (icons, splash, tab icons, latency-critical SFX) bundled.

The architectural seam is already in place: `ASSET_IMAGE_DIR` (`apps/server/src/image-assets.ts:2`, `apps/server/src/image-gen.ts:7`) and `ASYNC_AUDIO_DIR` (`apps/server/src/activities.ts:410`) are environment-overridable filesystem paths. This proposal replaces the filesystem backend with an S3 client wrapper while preserving the same `getImageDir()` / asset-ID-by-content-hash contracts.

## Problem statement

| Concern | Current state | Pain |
|---|---|---|
| Repo size | 179MB pack, ~195MB binary media (187 files) | Every clone — dev, CI, droplet, EAS — re-downloads everything |
| New content shipping | Bundled location art → app store release for each new location | "Lame to ship a new client to add a location" |
| Mobile bundle weight | `apps/mobile/assets/` ~53MB, ~28MB of that is content (locations 21MB + marketing 7MB) | App download size matters for cellular installs and update bandwidth |
| Generated content provenance | `image-gen.ts` writes new portraits to `assets/images/` on the server at runtime | These never make it back into git; lost when the droplet rolls |
| Git-LFS alternative | Cheaper to set up but rewrites history, locks us into GitHub LFS quotas ($5/50GB/month bandwidth) | Doesn't address the runtime-generated-asset problem; doesn't unlock per-location OTA shipping |

Object storage solves all five at once. LFS would solve only the first.

## Goals

1. **Git stays code-only.** All `.png`, `.jpg`, `.mp3`, `.wav` files under `assets/` and `apps/mobile/assets/images/{locations,marketing}/` move out of git. Pack size drops to <20MB.
2. **One asset store, two readers.** The same bucket serves both the Bun server (reads + writes, for the runtime portrait generator) and the Expo mobile app (reads only, for content art).
3. **Local dev parity.** Local development runs against a containerized S3-compatible server (rustfs in `docker-compose.yml`); no developer needs a real DO Spaces account to work on the project.
4. **Runtime-generated assets persist across deploys.** Droplet recycles don't lose generated portraits.
5. **New content ships without an app store release.** Location/marketing art is data, not code.
6. **App shell stays bundled.** Icons, splash, tab icons, and SFX (audio-first latency requirement) stay in the Expo bundle. Only content art moves remote.
7. **Failure modes are scoped.** Local dev keeps a filesystem-backend opt-out; mobile renders a bundled placeholder while the network fetch is in flight or fails. Prod server has no fs fallback by design (assets aren't on the droplet post-migration) — relies on Spaces uptime + bucket versioning for recovery.

## Non-goals

- **Versioned asset history.** Object storage replaces git for binaries; we accept losing per-commit asset diffs (git wasn't doing useful diffs for binaries anyway). Bucket versioning (Spaces supports it) is the safety net.
- **CDN edge caching.** Spaces fronts via DigitalOcean's CDN automatically; no separate CDN setup in this spec.
- **Auth-gated assets.** All migrated assets are public-readable; the existing `image-assets.ts` endpoint sanitizes the asset ID and the bucket gets the same content-addressable IDs. Per-user/per-tier asset gating is a future concern.
- **CI cost optimization beyond bucket existence.** CI uses the same bucket as local dev (rustfs container in CI workflow); we don't tune for "only test-e2e fetches assets" since fetches are free against a local container.

## Current state — concrete seams

### Server reads

| Path | Endpoint | Current backend | Reference |
|---|---|---|---|
| `assets/images/<id>.png` | `GET /api/assets/images/<id>` | `Bun.file()` from `ASSET_IMAGE_DIR` (default: top-level `assets/images/`) | `apps/server/src/image-assets.ts:5-23` |
| `<audio_dir>/<filename>` | `GET /api/audio/<filename>` | `Bun.file()` from `ASYNC_AUDIO_DIR` (default `${import.meta.dir}/../../audio` → `apps/audio/`, empty in repo — see Q4) | `apps/server/src/activities.ts:410-431` |

### Server writes

| Path | Trigger | Backend | Reference |
|---|---|---|---|
| `assets/images/<id>.png` | `image-gen.ts` runtime portrait generation (Gemini) | `Bun.write()` to `ASSET_IMAGE_DIR` | `apps/server/src/image-gen.ts:85` |
| `generated_assets` DB row | Same call | Postgres insert with `file_path` column | `apps/server/src/image-gen.ts:90`, `scripts/migrations/010_generated_assets.sql` |

### Mobile reads

| Path | Consumer | Current backend | Reference |
|---|---|---|---|
| `assets/images/locations/<id>.png` | `LocationArtEntry.bundled` via `require()` | Metro bundler — packaged into Expo build | `apps/mobile/src/constants/location-art-registry.ts:13-25` |
| `assets/images/marketing/*.png` | Marketing/onboarding screens (TBD) | Metro bundler | (audit during execution plan) |
| `assets/sounds/*.mp3` | `sound-registry.ts`, `music-registry.ts`, `soundscape-registry.ts` | Metro bundler | `apps/mobile/src/audio/*.ts` |
| `assets/images/{icon,splash,favicon,grain,android-icon-*}.png` | OS app shell | Metro / Expo build manifest | `app.json` |

## Proposed architecture

### Storage backends

| Environment | Backend | Bucket name | Notes |
|---|---|---|---|
| Local dev | rustfs container (S3-compatible) | `divineruin-assets-local` | Started by `docker-compose.yml` alongside Postgres + Redis. Single binary, ~10MB image. |
| CI (GitHub Actions) | rustfs service container | `divineruin-assets-ci` | `services:` block in `ci.yml`. Pre-populated by a seed step. |
| Production | DigitalOcean Spaces | `divineruin-assets-prod` | Spaces region matches droplet region. Versioning enabled. |

Same S3 API across all three — no code branching by environment.

### Server client wrapper

New file `apps/server/src/asset-storage.ts`:

```ts
interface AssetStorage {
  read(key: string): Response;            // streams; sets ETag + Cache-Control
  write(key: string, body: Buffer): Promise<void>;
  exists(key: string): Promise<boolean>;
}
```

Two implementations:
- `S3AssetStorage` — uses `@aws-sdk/client-s3` (or `Bun.s3` if Bun ships a native client suitable for self-hosted endpoints; check at execution time).
- (Optional) `FilesystemAssetStorage` — kept as a fallback for "I just want to hack locally without docker." Selected by `ASSET_STORAGE_BACKEND=filesystem|s3`.

`image-assets.ts`, `activities.ts` (audio handler), and `image-gen.ts` all rewrite to call the abstract `AssetStorage` interface instead of `Bun.file` / `Bun.write` directly. The env vars `ASSET_IMAGE_DIR` / `ASYNC_AUDIO_DIR` get repurposed as bucket prefixes (e.g., `S3_ASSETS_BUCKET=divineruin-assets-local`, `S3_IMAGES_PREFIX=images/`, `S3_AUDIO_PREFIX=audio/`) or retired entirely in favor of one canonical `S3_*` env trio (endpoint, region, access key, secret, bucket).

### Mobile client

`location-art-registry.ts` evolves from:

```ts
type LocationArtEntry = { bundled: number; category: ... };
```

to:

```ts
type LocationArtEntry = {
  remote: string;                                    // `images/locations/<id>.png` key
  fallback?: number;                                 // bundled placeholder for first-render
  category: "town" | "interior" | "wilderness" | "corrupted";
};
```

A new `apps/mobile/src/asset-loader/` module:
- Fetches `<EXPO_PUBLIC_API_URL>/api/assets/images/<key>` (or a direct bucket URL if we expose one).
- Caches in `expo-file-system` (persistent local cache, content-addressable by URL).
- Pre-fetches on `session_init` + `location_changed` events to keep the audio-first invariant (art ready before the DM names the location).
- Falls back to `fallback` bundled placeholder if the network fetch fails or is in flight.

### Upload tooling

New `scripts/upload_assets.ts`:
- Walks `assets/**` and `apps/mobile/assets/images/{locations,marketing}/**`.
- Computes content hashes (matches existing `computeAssetId` convention in `image-gen.ts:11-17`).
- Uploads to the configured bucket with `Content-Type` + `Cache-Control: public, max-age=86400` (matches existing handler headers).
- Idempotent: skip if the object already exists with the same hash.
- Dry-run mode for verification.

Triggered manually during migration; can also wire into `seed_content.py` (or its successor) for the location/marketing asset onboarding flow.

### Database

Keep `generated_assets` table (`scripts/migrations/010_generated_assets.sql`). Add a `storage_backend` column (or just rely on `file_path` being a bucket key by convention) so we can distinguish migration-uploaded vs runtime-generated.

## Migration path (rough — for execution plan to refine)

1. **Bucket + client wrapper land first.** Spin up rustfs locally, write `asset-storage.ts`, refactor server handlers to use it. At this point both backends still work (env-switchable). Tests cover both.
2. **Upload script + dual-read window.** Run `upload_assets.ts` to populate local + prod buckets. Server reads from bucket by default; filesystem read remains as fallback. Existing `assets/**` stays in git for one more sprint.
3. **Mobile refactor.** `location-art-registry.ts` shape change + `asset-loader/` module + pre-fetch wiring. Bundled location PNGs become `fallback: require(...)` for the first session before cache warms.
4. **Remove from git.** Delete `assets/**` + `apps/mobile/assets/images/locations/**` + `apps/mobile/assets/images/marketing/**` from git in a single commit. Pack size drops. Repo no longer ships binaries.
5. **(Optional cleanup) Drop the filesystem backend** once production has run on S3 for a sprint without issues.

The execution plan should decide each step's commit shape, test coverage, and any feature-flag rollback hooks.

## Open questions for the execution plan

1. **rustfs vs MinIO** for local dev. rustfs is newer, single-binary, ~10MB image. MinIO is the de-facto standard, more familiar, ~50MB image. Either works; rustfs is the lighter default.
2. **Bun-native S3 client** (`Bun.s3`, available in Bun 1.1.30+) vs **`@aws-sdk/client-s3`**. Bun-native is faster + zero deps but verify it handles self-hosted endpoints (custom `endpoint` + path-style addressing) cleanly. Pick at execution time based on current Bun version.
3. **Direct bucket URL vs server-proxied reads.** Mobile could fetch `https://<spaces-region>.digitaloceanspaces.com/divineruin-assets-prod/images/locations/<id>.png` directly (cheaper, fewer hops) OR continue through `<api>/api/assets/images/<id>` (auth-ready, request-logged, easier to swap backends). Recommend server-proxied initially; switch to direct CDN URLs later if bandwidth costs justify.
4. **What about top-level `assets/audio/`?** Currently has 6 MP3s; `ASYNC_AUDIO_DIR` defaults to `${import.meta.dir}/../../audio` which resolves to `apps/audio/` (truly empty in the repo — no files, no `.gitkeep`) — so the handler 404s in dev unless `ASYNC_AUDIO_DIR=assets/audio` is set. Migration is a good time to fix the default to point at `assets/audio/` (or the bucket prefix) + audit what's actually in `assets/audio/`.
5. **Spaces cost model.** DO Spaces is $5/month for 250GB storage + 1TB egress. Well within budget for current asset volume (~195MB) + projected growth. Revisit if asset library 10×s.
6. **Backup strategy.** Spaces versioning protects against accidental overwrites. Periodic full-bucket snapshot to a different region for disaster recovery? Out of scope for v1.
7. **Asset deletion.** What happens when a location is removed from `content/locations.json`? Stale bucket objects accumulate. Add a `prune` mode to `upload_assets.ts` or accept the cost.
8. **Test fixture story.** Server tests today create test PNGs via `sharp.toBuffer()` + `Bun.write()` (see `apps/server/src/image-assets.test.ts:36-52`). With S3 backend, tests need to write through the `AssetStorage` interface — either point at a per-test in-memory mock or at the rustfs container. Pick a pattern early.

## References

- `apps/server/src/image-assets.ts` — server image-serving endpoint
- `apps/server/src/image-gen.ts` — runtime portrait generator (Gemini)
- `apps/server/src/activities.ts:410-431` — audio file serving
- `apps/mobile/src/constants/location-art-registry.ts` — mobile location art map (current shape)
- `apps/mobile/src/audio/sound-registry.ts`, `music-registry.ts`, `soundscape-registry.ts` — bundled audio (stays bundled per audio-first invariant)
- `scripts/migrations/010_generated_assets.sql` — DB schema for asset metadata
- `scripts/seed_content.py` — content-seeding flow (asset-adjacent)
- ADR 0001 — `docs/decisions/0001-patron-roster-sot.md` — for spec/proposal style reference (this doc is less formal; an ADR can land later when the decision crystallizes)
