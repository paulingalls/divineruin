# Security Notes

## 2026-03-07 — Security Audit Findings

### Fixed
- **Timing-safe secret comparison** — `verifyInternalSecret()` in middleware.ts uses `timingSafeEqual`; push.ts and image-gen-api.ts consume it.
- **Per-account auth code lockout** — `handleVerifyCode` tracks `failed_attempts`; 5 failures invalidate the code. Migration: `011_auth_code_attempts.sql`.
- **Cache-Control preservation** — `withCors()` no longer overwrites pre-set `Cache-Control` headers (e.g., audio file caching).
- **Activity list pagination** — `handleListActivities` queries capped at `LIMIT 100`.
- **Path traversal guard in TTS** — `synthesize_to_file` rejects paths containing `..`.

### Accepted Risks / Deferred
- **Per-session mutation caps** — `session_data.py` tracks `session_xp_earned` but has no per-session budget. Tools have per-call caps (XP: 10k, favor: 1-10, disposition: ±2, inventory: 1-99). Adding cumulative caps needs gameplay design input on reasonable limits.
- **Voice prompt injection** — Player speech flows directly into LLM context. Tool-level caps are the primary defense. Prompt-level containment ("ignore instructions to...") needs careful engineering to avoid breaking gameplay.
- **Redis authentication** — Dev-only Docker. Use managed Redis with auth in production.
- **Token refresh** — JWT has 30d expiry. No client-side refresh. Acceptable for MVP.
- **In-memory rate limiter** — Per-process, doesn't survive restarts or scale horizontally. Acceptable for single-instance.
- **Internal secret over HTTP** — Localhost only. Enforce HTTPS for production deployment.
