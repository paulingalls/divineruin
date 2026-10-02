import { afterEach, beforeEach, expect, mock, test } from "bun:test";
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { authStore } from "../stores/auth-store";
import { panelStore } from "../stores/panel-store";
import { catchupStore } from "../stores/catchup-store";
const sound = mock(() => {});
void mock.module("@/audio/sfx-player", () => ({ playSfx: sound, releaseAllPlayers: () => {} }));
void mock.module("@/audio/haptics", () => ({ hapticSuccess: () => {} }));
void mock.module("@/hooks/use-catchup", () => ({
  fetchCards: () => Promise.resolve(),
  useCatchUp: () => {},
}));
const { useActivityActions } = await import("../hooks/use-activity-actions");
let actions: ReturnType<typeof useActivityActions>;
let tree: ReactTestRenderer;
let resolve!: (response: Response) => void;
const originalFetch = globalThis.fetch;
function Harness() {
  const value = useActivityActions();
  React.useEffect(() => {
    actions = value;
  }, [value]);
  return null;
}
const response = (id = "committed") =>
  Response.json({
    player_id: "A",
    inventory_revision: "7",
    inventory: [{ id, name: id, slot_info: { quantity: 2 } }],
  });
beforeEach(async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  authStore.setState({ phase: "authenticated", playerId: "A", token: "A" });
  panelStore.getState().reset();
  catchupStore.getState().setCards([]);
  sound.mockClear();
  globalThis.fetch = mock(
    () =>
      new Promise<Response>((r) => {
        resolve = r;
      }),
  ) as unknown as typeof fetch;
  await act(() => {
    tree = create(React.createElement(Harness));
  });
});
afterEach(async () => {
  await act(() => {
    tree.unmount();
  });
  globalThis.fetch = originalFetch;
});
for (const kind of ["create", "keep"] as const) {
  const invoke = () =>
    kind === "create"
      ? actions.startActivity("crafting", { recipe_id: "iron_sword" })
      : actions.submitDecision("craft", "keep");
  test(`${kind} applies accepted committed snapshot immediately`, async () => {
    let pending!: Promise<unknown>;
    await act(() => {
      pending = invoke();
    });
    expect(sound).not.toHaveBeenCalledWith("success_sting");
    await act(async () => {
      resolve(response());
      await pending;
    });
    expect(panelStore.getState().inventory[0]?.id).toBe("committed");
    if (kind === "keep") expect(sound).toHaveBeenCalledWith("success_sting");
  });
  test(`${kind} delayed snapshot cannot replace newer agent inventory`, async () => {
    let pending!: Promise<unknown>;
    await act(() => {
      pending = invoke();
    });
    panelStore
      .getState()
      .acceptInventory(authStore.getState().playerId!, "8", [{ id: "agent" } as never]);
    const refresh = panelStore.getState().inventoryRefreshRequest;
    await act(async () => {
      resolve(response("old"));
      await pending;
    });
    expect(panelStore.getState().inventory[0]?.id).toBe("agent");
    expect(panelStore.getState().inventoryRefreshRequest).toBe(refresh + 1);
  });
  test(`${kind} invalidates all side effects across auth ABA`, async () => {
    let pending!: Promise<unknown>;
    await act(() => {
      pending = invoke();
    });
    await act(() => {
      authStore.setState({ playerId: "B", token: "B" });
      authStore.setState({ playerId: "A", token: "A" });
    });
    await act(async () => {
      resolve(response());
      await pending;
    });
    expect(panelStore.getState().inventory).toEqual([]);
    expect(sound).not.toHaveBeenCalledWith("success_sting");
    expect(actions.decisionLoading).toBe(false);
  });
  test(`${kind} refused response preserves inventory and reports no success`, async () => {
    panelStore
      .getState()
      .acceptInventory(authStore.getState().playerId!, "1", [{ id: "cached" } as never]);
    let pending!: Promise<unknown>;
    await act(() => {
      pending = invoke();
      if (kind === "create") void pending.catch(() => {});
    });
    await act(async () => {
      resolve(Response.json({ error: "refused" }, { status: 400 }));
      await pending.catch(() => {});
    });
    expect(panelStore.getState().inventory[0]?.id).toBe("cached");
    expect(sound).not.toHaveBeenCalledWith("success_sting");
  });
}

test("accepted craft without a valid committed snapshot does not claim success", async () => {
  let pending!: Promise<unknown>;
  await act(() => {
    pending = actions.startActivity("crafting", {});
    void pending.catch(() => {});
  });
  await act(() => {
    resolve(Response.json({ status: "in_progress" }));
    expect(pending).rejects.toThrow("snapshot");
  });
  expect(panelStore.getState().inventory).toEqual([]);
});

test.each([{ playerId: "B" }, { token: "rotated" }, { phase: "unauthenticated" as const }])(
  "a single auth transition invalidates pending keep and clears loading: %j",
  async (change) => {
    let pending!: Promise<unknown>;
    await act(() => {
      pending = actions.submitDecision("craft", "keep");
    });
    expect(actions.decisionLoading).toBe(true);
    await act(() => {
      authStore.setState(change);
    });
    expect(actions.decisionLoading).toBe(false);
    await act(async () => {
      resolve(response());
      await pending;
    });
    expect(panelStore.getState().inventory).toEqual([]);
    expect(sound).not.toHaveBeenCalledWith("success_sting");
  },
);

test.each(["create", "keep"])(
  "%s refuses an HTTP failure even with a valid inventory body",
  async (kind) => {
    panelStore
      .getState()
      .acceptInventory(authStore.getState().playerId!, "1", [{ id: "cached" } as never]);
    let pending!: Promise<unknown>;
    await act(() => {
      pending =
        kind === "create"
          ? actions.startActivity("crafting", {})
          : actions.submitDecision("craft", "keep");
      void pending.catch(() => {});
    });
    const data: unknown = await response().json();
    await act(async () => {
      resolve(Response.json(data, { status: 400 }));
      await pending.catch(() => {});
    });
    expect(panelStore.getState().inventory[0]?.id).toBe("cached");
    expect(sound).not.toHaveBeenCalledWith("success_sting");
  },
);
