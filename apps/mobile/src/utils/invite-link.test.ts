import { test, expect } from "bun:test";
import { firstInviteCode } from "./invite-link";

test("firstInviteCode: array coercion — returns first element of repeated query key", () => {
  expect(firstInviteCode(["A", "B"])).toBe("A");
});

test("firstInviteCode: scalar passthrough — returns single string as-is", () => {
  expect(firstInviteCode("solo")).toBe("solo");
});

test("firstInviteCode: absent key — returns undefined", () => {
  expect(firstInviteCode(undefined)).toBeUndefined();
});

test("firstInviteCode: empty array edge case — returns undefined", () => {
  expect(firstInviteCode([])).toBeUndefined();
});
