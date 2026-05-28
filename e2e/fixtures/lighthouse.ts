// Single source of truth for the Lighthouse capstone's Chrome remote-debugging
// port. The web-lighthouse Playwright project launches its fixture browser with
// `--remote-debugging-port=<this>` (playwright.config.ts) and the capstone spec
// passes the same value to playAudit so it attaches to that browser
// (web-production.e2e.ts). They MUST match — a mismatch makes playAudit attach to
// nothing (hang) instead of failing loud — so both import this constant rather
// than repeating the literal.
export const LH_DEBUG_PORT = 9222;
