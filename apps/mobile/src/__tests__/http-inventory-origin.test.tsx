import { afterEach, expect, mock, test } from "bun:test";
import { resolve } from "node:path";
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { authStore } from "../stores/auth-store";
import { panelStore } from "../stores/panel-store";
const CONTRACT_CHILD = "DIVINERUIN_HTTP_ORIGIN_CONTRACT_CHILD";

// Bun module mocks persist across files; keep this mounted route's partial
// component and router mocks inside its own process.
if (process.env[CONTRACT_CHILD] === "1") {
  let fixture = "https://attacker.example";
  void mock.module("expo-router", () => ({ useLocalSearchParams: () => ({ fixture }) }));
  void mock.module("@/components/themed-text", () => ({ ThemedText: "Text" }));
  void mock.module("@/components/hud/panels/inventory-panel", () => ({
    InventoryPanel: () => null,
  }));
  const { default: HttpInventoryTest } = await import("../app/http-inventory-test");
  const originalFetch = globalThis.fetch;
  let tree: ReactTestRenderer | undefined;
  afterEach(async () => {
    await act(() => tree?.unmount());
    tree = undefined;
    globalThis.fetch = originalFetch;
  });
  test.each([
    "https://attacker.example",
    "http://attacker.example",
    "https://127.0.0.1",
    "http://user@127.0.0.1",
    "http://:secret@127.0.0.1",
    "http://127.0.0.1@attacker.example",
    "invalid",
  ])("mounted invalid fixture %s sends no observation or control requests", async (origin) => {
    fixture = origin;
    (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT =
      true;
    authStore.setState({ phase: "authenticated", playerId: "prior", token: "token" });
    panelStore.getState().openPanel();
    panelStore
      .getState()
      .acceptInventory(authStore.getState().playerId!, "1", [
        { id: "oak_wood", quantity: 37 } as never,
      ]);
    const outbound = mock(() => Promise.resolve(Response.json({})));
    globalThis.fetch = outbound as unknown as typeof fetch;
    await act(async () => {
      tree = create(<HttpInventoryTest />);
      await Promise.resolve();
    });
    expect(JSON.stringify(tree!.toJSON())).toContain("Fixture must be loopback HTTP");
    for (const button of tree!.root.findAllByType("Pressable" as never)) {
      await act(async () => {
        (button.props as { onPress: () => void }).onPress();
        await Promise.resolve();
      });
    }
    expect(outbound).not.toHaveBeenCalled();
    expect(panelStore.getState()).toMatchObject({
      inventoryOwner: "prior",
      inventoryRevision: "1",
      inventory: [{ id: "oak_wood", quantity: 37 }],
    });
  });
} else {
  test("all mounted invalid-origin guards pass in an isolated module process", async () => {
    const child = Bun.spawn(["bun", "test", "src/__tests__/http-inventory-origin.test.tsx"], {
      cwd: resolve(import.meta.dir, "../.."),
      env: { ...process.env, [CONTRACT_CHILD]: "1" },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]);
    const output = `${stdout}\n${stderr}`;
    expect(exitCode, output).toBe(0);
    expect(output).toMatch(/\b7 pass\b/);
    expect(output).toMatch(/\b0 fail\b/);
  });
}
