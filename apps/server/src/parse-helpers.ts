// Canonical fail-loud coercion helpers for content-row parsers (items.ts, recipes.ts).
// Each throws an Error whose message carries the caller's `ctx` so the failing field is
// identifiable. Single source of truth — do not re-inline these checks (debt aa2c0bf5c147).

/** Coerce an unknown to a plain object record, rejecting null, non-objects, and arrays. */
export function asRecord(raw: unknown, ctx: string): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`${ctx} is not an object`);
  }
  return raw as Record<string, unknown>;
}

/** Coerce an unknown to a string, rejecting any non-string with the caller's ctx. */
export function parseString(raw: unknown, ctx: string): string {
  if (typeof raw !== "string") throw new Error(`${ctx} is not a string`);
  return raw;
}

/** Parse an unknown into a string[], rejecting non-arrays and non-string elements. */
export function parseStringArray(raw: unknown, ctx: string): string[] {
  if (!Array.isArray(raw)) throw new Error(`${ctx} is not an array`);
  return raw.map((v, i) => {
    if (typeof v !== "string") throw new Error(`${ctx}[${i}] is not a string`);
    return v;
  });
}
