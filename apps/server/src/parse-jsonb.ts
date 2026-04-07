/** Parse a JSONB column value — Bun.sql may return it as string or object. */
export function parseJsonb<T = Record<string, unknown>>(val: unknown): T {
  return (typeof val === "string" ? JSON.parse(val) : val) as T;
}
