export function requireEnv(name: string): string {
  const value = Bun.env[name];
  if (!value) {
    throw new Error(`${name} is not set`);
  }
  return value;
}

export const isDev = Bun.env.NODE_ENV !== "production";

// True under any test runner. Without this guard, code that calls external APIs
// (Resend, etc.) would hit production endpoints during test runs.
export const IS_TEST_ENV = Bun.env.NODE_ENV === "test" || Bun.env.BUN_TEST === "1";

export function logError(label: string, err: unknown): void {
  if (isDev) {
    console.error(label, err);
  } else {
    console.error(label, err instanceof Error ? err.message : String(err));
  }
}

// Env-gated structured diagnostic. Off unless E2E_DIAG=1 (set by the e2e
// webServer) so flake artifacts capture server-side state without adding noise
// to normal dev/prod runs. The payload is a thunk so callers pay nothing for
// it when the gate is off — no reduce/map/serialize on the prod/dev hot path.
// One JSON line per call for easy grep in the persisted pre-push log.
export function logDiag(label: string, dataFn: () => Record<string, unknown>): void {
  if (Bun.env.E2E_DIAG !== "1") return;
  console.log(`[diag] ${label} ${JSON.stringify(dataFn())}`);
}
