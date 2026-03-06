export function requireEnv(name: string): string {
  const value = Bun.env[name];
  if (!value) {
    throw new Error(`${name} is not set`);
  }
  return value;
}

export const isDev = process.env.NODE_ENV !== "production";

export function logError(label: string, err: unknown): void {
  if (isDev) {
    console.error(label, err);
  } else {
    console.error(label, err instanceof Error ? err.message : String(err));
  }
}
