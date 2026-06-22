import { test, expect, describe, spyOn, afterEach } from "bun:test";

import { logDiag } from "./env.ts";

const ORIGINAL_E2E_DIAG = Bun.env.E2E_DIAG;

afterEach(() => {
  // Restore the env flag so lane/test order can never leak it (logDiag reads
  // Bun.env.E2E_DIAG at call time, so a stuck flag would taint later tests).
  if (ORIGINAL_E2E_DIAG === undefined) {
    delete Bun.env.E2E_DIAG;
  } else {
    Bun.env.E2E_DIAG = ORIGINAL_E2E_DIAG;
  }
});

describe("logDiag", () => {
  test("is silent when E2E_DIAG is unset", () => {
    delete Bun.env.E2E_DIAG;
    const spy = spyOn(console, "log").mockImplementation(() => {});
    try {
      logDiag("catchup.feed", () => ({ total: 3 }));
      expect(spy).not.toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });

  test("is silent when E2E_DIAG is not exactly '1'", () => {
    Bun.env.E2E_DIAG = "true";
    const spy = spyOn(console, "log").mockImplementation(() => {});
    try {
      logDiag("catchup.feed", () => ({ total: 3 }));
      expect(spy).not.toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });

  test("does not invoke the payload thunk when the gate is off", () => {
    delete Bun.env.E2E_DIAG;
    let invoked = false;
    logDiag("catchup.feed", () => {
      invoked = true;
      return { total: 3 };
    });
    expect(invoked).toBe(false);
  });

  test("emits one parseable JSON line when E2E_DIAG='1'", () => {
    Bun.env.E2E_DIAG = "1";
    const spy = spyOn(console, "log").mockImplementation(() => {});
    try {
      logDiag("catchup.feed", () => ({ total: 3, ids: ["a", "b"] }));
      expect(spy).toHaveBeenCalledTimes(1);
      const line = spy.mock.calls[0]![0] as string;
      expect(line.startsWith("[diag] catchup.feed ")).toBe(true);
      const json = line.slice("[diag] catchup.feed ".length);
      expect(JSON.parse(json)).toEqual({ total: 3, ids: ["a", "b"] });
    } finally {
      spy.mockRestore();
    }
  });
});
