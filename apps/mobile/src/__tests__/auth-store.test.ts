import { beforeEach, describe, expect, test } from "bun:test";

import { authStore } from "@/stores/auth-store";
import { pendingInviteStore } from "@/stores/pending-invite-store";

describe("auth-store", () => {
  beforeEach(() => {
    authStore.setState({
      phase: "loading",
      email: null,
      token: null,
      accountId: null,
      playerId: null,
    });
    pendingInviteStore.setState({ code: null });
  });

  test("logout clears the pending invite code", async () => {
    pendingInviteStore.getState().setPendingCode("INVITE_CODE_X");
    expect(pendingInviteStore.getState().code).toBe("INVITE_CODE_X");

    await authStore.getState().logout();

    expect(pendingInviteStore.getState().consumePendingCode()).toBeNull();
  });

  test("logout sets phase to unauthenticated", async () => {
    await authStore.getState().logout();
    expect(authStore.getState().phase).toBe("unauthenticated");
  });
});
