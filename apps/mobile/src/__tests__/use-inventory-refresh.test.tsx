import { afterEach, beforeEach, expect, mock, test } from "bun:test";
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { authStore } from "../stores/auth-store";
import { panelStore } from "../stores/panel-store";
let appState = "active";
let listener: ((state: string) => void) | undefined;
const { AppState } = await import("react-native");
Object.defineProperty(AppState, "currentState", { get: () => appState, configurable: true });
AppState.addEventListener = ((_: string, callback: typeof listener) => {
  listener = callback;
  return {
    remove: () => {
      listener = undefined;
    },
  };
}) as typeof AppState.addEventListener;
const { useInventoryRefresh } = await import("../hooks/use-inventory-refresh");
const originalFetch = globalThis.fetch;
const originalInterval = globalThis.setInterval;
const originalClear = globalThis.clearInterval;
let now = 0;
let interval: { callback: () => void; next: number; ms: number } | undefined;
let requests: { resolve: (response: Response) => void; reject: (error: Error) => void }[];
let tree: ReactTestRenderer | undefined;
const item = (id: string) => ({ id, name: id, slot_info: { quantity: 1 } });
const snapshot = (id: string, owner = "A") =>
  Response.json({ player_id: owner, inventory: [item(id)] });
function Harness() {
  useInventoryRefresh();
  return null;
}
const flush = (fn: () => void = () => {}) =>
  act(async () => {
    fn();
    await Promise.resolve();
  });
async function mount() {
  await act(() => {
    tree = create(<Harness />);
  });
}
async function tick(ms: number) {
  await flush(() => {
    now += ms;
    if (interval && now >= interval.next) {
      interval.next += interval.ms;
      interval.callback();
    }
  });
}
beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  now = 0;
  interval = undefined;
  requests = [];
  appState = "active";
  panelStore.getState().reset();
  authStore.setState({ phase: "authenticated", playerId: "A", token: "token-A" });
  globalThis.fetch = mock(
    () =>
      new Promise<Response>((resolve, reject) => {
        requests.push({ resolve, reject });
      }),
  ) as unknown as typeof fetch;
  globalThis.setInterval = ((callback: () => void, ms: number) => {
    interval = { callback, ms, next: now + ms };
    return 1;
  }) as unknown as typeof setInterval;
  globalThis.clearInterval = () => {
    interval = undefined;
  };
});
afterEach(async () => {
  await act(() => {
    tree?.unmount();
  });
  tree = undefined;
  globalThis.fetch = originalFetch;
  globalThis.setInterval = originalInterval;
  globalThis.clearInterval = originalClear;
});
test("opening any HUD refreshes, foreground polls at five seconds and allows one in-flight", async () => {
  await mount();
  expect(requests).toHaveLength(0);
  await flush(() => panelStore.getState().openPanel("quests"));
  expect(requests).toHaveLength(1);
  await tick(5000);
  expect(requests).toHaveLength(1);
  await flush(() => requests[0].resolve(snapshot("first")));
  expect(panelStore.getState().inventory[0]?.id).toBe("first");
  await tick(4999);
  expect(requests).toHaveLength(1);
  await tick(1);
  expect(requests).toHaveLength(2);
});
test("background/close/unmount stop polling, resume refreshes and ignored abort cannot apply", async () => {
  panelStore.getState().openPanel();
  await mount();
  expect(requests).toHaveLength(1);
  await flush(() => listener!("background"));
  expect(interval).toBeUndefined();
  await flush(() => requests[0].resolve(snapshot("obsolete")));
  expect(panelStore.getState().inventory).toEqual([]);
  await flush(() => listener!("active"));
  expect(requests).toHaveLength(2);
  await flush(() => panelStore.getState().closePanel());
  expect(interval).toBeUndefined();
  await flush(() => requests[1].resolve(snapshot("closed")));
  expect(panelStore.getState().inventory).toEqual([]);
  await flush(() => panelStore.getState().openPanel());
  expect(requests).toHaveLength(3);
  await act(() => {
    tree!.unmount();
  });
  tree = undefined;
  expect(listener).toBeUndefined();
  expect(interval).toBeUndefined();
  await flush(() => requests[2].resolve(snapshot("unmounted")));
  expect(panelStore.getState().inventory).toEqual([]);
});
test.each(["agent", "mutation"])(
  "newer %s snapshot discards pending GET and fetches fresh",
  async () => {
    panelStore.getState().openPanel();
    await mount();
    await flush(() => panelStore.getState().setInventory([{ id: "newer" } as never]));
    await flush(() => requests[0].resolve(snapshot("old")));
    expect(panelStore.getState().inventory[0]?.id).toBe("newer");
    expect(requests).toHaveLength(2);
    await flush(() => requests[1].resolve(snapshot("fresh")));
    expect(panelStore.getState().inventory[0]?.id).toBe("fresh");
    expect(requests).toHaveLength(2);
  },
);
test("logout and player ABA invalidate pending identity even when credentials return", async () => {
  panelStore.getState().openPanel();
  await mount();
  await flush(() => {
    authStore.setState({ playerId: "B", token: "B" });
    authStore.setState({ playerId: "A", token: "token-A" });
  });
  await flush(() => requests[0].resolve(snapshot("old-A")));
  expect(panelStore.getState().inventory).toEqual([]);
  expect(requests).toHaveLength(2);
  await flush(() => authStore.setState({ phase: "unauthenticated", token: null, playerId: null }));
  await flush(() => requests[1].resolve(snapshot("logged-out")));
  expect(panelStore.getState().inventory).toEqual([]);
  expect(interval).toBeUndefined();
});
test.each(["http", "network", "malformed"])(
  "%s failure preserves data, reports error and retries on scheduled poll",
  async (kind) => {
    panelStore.getState().setInventory([{ id: "cached" } as never]);
    panelStore.getState().openPanel();
    await mount();
    await flush(() => {
      if (kind === "network") requests[0].reject(new Error("offline"));
      else
        requests[0].resolve(
          kind === "http" ? new Response("bad", { status: 500 }) : Response.json({ inventory: [] }),
        );
    });
    expect(panelStore.getState().inventory[0]?.id).toBe("cached");
    expect(panelStore.getState().inventoryRefreshError).toContain("Inventory refresh failed");
    expect(requests).toHaveLength(1);
    await tick(5000);
    expect(requests).toHaveLength(2);
    await flush(() => requests[1].resolve(snapshot("recovered")));
    expect(panelStore.getState().inventoryRefreshError).toBeNull();
  },
);
test("background and unauthenticated mount do not fetch", async () => {
  appState = "background";
  panelStore.getState().openPanel();
  await mount();
  expect(requests).toHaveLength(0);
  await flush(() => {
    authStore.setState({ phase: "unauthenticated" });
    listener!("active");
  });
  expect(requests).toHaveLength(0);
});

test.each([
  { player_id: "B", inventory: [] },
  { player_id: "A", inventory: null },
  { player_id: "A", inventory: "" },
  { player_id: "A", inventory: [null] },
  { player_id: "A", inventory: [{ name: "missing-id", slot_info: {} }] },
  { player_id: "A", inventory: [{ id: "missing-name", slot_info: {} }] },
  { player_id: "A", inventory: [{ id: "missing-slot", name: "missing-slot" }] },
  { player_id: "A", inventory: [{ id: "null-slot", name: "null-slot", slot_info: null }] },
  { player_id: "A", inventory: [{ id: "invalid-slot", name: "invalid-slot", slot_info: true }] },
  { player_id: "A", inventory: [{ id: "array-slot", name: "array-slot", slot_info: [] }] },
  { player_id: "A", inventory: [{ id: "bad-quantity", name: "bad", slot_info: { quantity: -1 } }] },
])("invalid HTTP snapshot preserves data and surfaces failure: %j", async (data) => {
  panelStore.getState().setInventory([{ id: "cached" } as never]);
  panelStore.getState().openPanel();
  await mount();
  await flush(() => requests[0].resolve(Response.json(data)));
  expect(panelStore.getState().inventory[0]?.id).toBe("cached");
  expect(panelStore.getState().inventoryRefreshError).toContain("Inventory refresh failed");
});

test.each(["background", "close"])(
  "%s then reopen rejects the still-pending old lifecycle response",
  async (kind) => {
    panelStore.getState().openPanel();
    await mount();
    await flush(() => {
      if (kind === "background") {
        listener!("background");
        listener!("active");
      } else {
        panelStore.getState().closePanel();
        panelStore.getState().openPanel();
      }
    });
    expect(requests).toHaveLength(1);
    await flush(() => requests[0].resolve(snapshot("old-lifecycle")));
    expect(panelStore.getState().inventory).toEqual([]);
    expect(requests).toHaveLength(2);
  },
);
