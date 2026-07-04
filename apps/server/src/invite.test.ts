import { test, expect, describe } from "bun:test";

const { generateCode } = await import("./invite.ts");

describe("generateCode", () => {
  test("produces a URL-safe, high-entropy code", () => {
    const code = generateCode();
    expect(code.length).toBeGreaterThanOrEqual(10);
    expect(code).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  test("produces distinct codes across calls", () => {
    const codes = new Set(Array.from({ length: 20 }, () => generateCode()));
    expect(codes.size).toBe(20);
  });
});
