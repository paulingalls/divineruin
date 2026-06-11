import { test, expect, describe } from "bun:test";
import { asRecord, parseString, parseStringArray } from "./parse-helpers.ts";

describe("asRecord", () => {
  test("returns a plain object unchanged", () => {
    const obj = { a: 1 };
    expect(asRecord(obj, "ctx")).toBe(obj);
  });

  test("rejects null/undefined/non-object/array with ctx in the message", () => {
    expect(() => asRecord(null, "items[x]")).toThrow("items[x] is not an object");
    expect(() => asRecord(undefined, "items[x]")).toThrow("items[x] is not an object");
    expect(() => asRecord("str", "items[x]")).toThrow("items[x] is not an object");
    expect(() => asRecord(42, "items[x]")).toThrow("items[x] is not an object");
    expect(() => asRecord([1, 2], "items[x]")).toThrow("items[x] is not an object");
  });
});

describe("parseString", () => {
  test("returns a string unchanged", () => {
    expect(parseString("hello", "ctx")).toBe("hello");
    expect(parseString("", "ctx")).toBe("");
  });

  test("rejects null/undefined/number/object with ctx in the message", () => {
    expect(() => parseString(null, "a.name")).toThrow("a.name is not a string");
    expect(() => parseString(undefined, "a.name")).toThrow("a.name is not a string");
    expect(() => parseString(42, "a.name")).toThrow("a.name is not a string");
    expect(() => parseString({}, "a.name")).toThrow("a.name is not a string");
  });
});

describe("parseStringArray", () => {
  test("returns the string array unchanged", () => {
    expect(parseStringArray(["a", "b"], "ctx")).toEqual(["a", "b"]);
    expect(parseStringArray([], "ctx")).toEqual([]);
  });

  test("rejects a non-array with ctx", () => {
    expect(() => parseStringArray("a", "r.sources")).toThrow("r.sources is not an array");
    expect(() => parseStringArray({}, "r.sources")).toThrow("r.sources is not an array");
  });

  test("rejects a non-string element with indexed ctx", () => {
    expect(() => parseStringArray(["a", 2], "r.sources")).toThrow("r.sources[1] is not a string");
  });
});
