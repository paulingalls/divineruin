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
