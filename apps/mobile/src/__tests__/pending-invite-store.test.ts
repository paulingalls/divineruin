import { beforeEach, describe, expect, test } from "bun:test";

import { pendingInviteStore } from "@/stores/pending-invite-store";

describe("pending-invite-store", () => {
  beforeEach(() => {
    pendingInviteStore.setState({ code: null });
  });

  test("set then consume returns the code and clears it", () => {
    pendingInviteStore.getState().setPendingCode("ABC123");
    expect(pendingInviteStore.getState().code).toBe("ABC123");

    expect(pendingInviteStore.getState().consumePendingCode()).toBe("ABC123");
    expect(pendingInviteStore.getState().code).toBeNull();
  });

  test("consume with nothing pending returns null", () => {
    expect(pendingInviteStore.getState().consumePendingCode()).toBeNull();
  });

  test("consume is single-shot — a second consume returns null", () => {
    pendingInviteStore.getState().setPendingCode("XYZ");
    expect(pendingInviteStore.getState().consumePendingCode()).toBe("XYZ");
    expect(pendingInviteStore.getState().consumePendingCode()).toBeNull();
  });
});
