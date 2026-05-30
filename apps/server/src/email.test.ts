import { test, expect } from "bun:test";
import { normalizeEmail, EMAIL_RE, MAX_EMAIL_LENGTH } from "./email.ts";

// Shared email validator extracted from auth.ts so the auth + waitlist endpoints
// validate identically. Pure function — no DOM, no DB — so it unit-tests directly.

test("accepts a valid address and normalizes it (trim + lowercase)", () => {
  expect(normalizeEmail("  Test.User@Example.COM ")).toBe("test.user@example.com");
  expect(normalizeEmail("a@b.co")).toBe("a@b.co");
});

test("rejects malformed addresses", () => {
  for (const bad of ["", "  ", "no-at", "no@tld", "@nolocal.com", "spaces in@x.com", "a@b"]) {
    expect(normalizeEmail(bad)).toBeNull();
  }
});

test("rejects undefined / missing input", () => {
  expect(normalizeEmail(undefined)).toBeNull();
});

test("rejects an address longer than MAX_EMAIL_LENGTH", () => {
  const longLocal = "x".repeat(MAX_EMAIL_LENGTH); // local-part alone exceeds the cap
  expect(normalizeEmail(`${longLocal}@example.com`)).toBeNull();
});

test("MAX_EMAIL_LENGTH is the RFC-ish 254 cap auth.ts used", () => {
  expect(MAX_EMAIL_LENGTH).toBe(254);
});

test("EMAIL_RE is exported for callers that need the raw matcher", () => {
  expect(EMAIL_RE.test("ok@example.com")).toBe(true);
  expect(EMAIL_RE.test("bad")).toBe(false);
});
