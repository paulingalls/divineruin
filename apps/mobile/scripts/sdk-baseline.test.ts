import { afterEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { verifySdk57Baseline } from "./sdk-baseline";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "sdk-57-baseline-"));
  roots.push(root);
  await mkdir(join(root, "apps/mobile"), { recursive: true });
  await writeFile(
    join(root, "package.json"),
    JSON.stringify({ overrides: { "dnssd-advertise": "1.1.4" } }),
  );
  await writeFile(
    join(root, "apps/mobile/package.json"),
    JSON.stringify({
      dependencies: {
        expo: "57.0.24",
        "expo-build-properties": "57.0.21",
        "@livekit/react-native": "2.12.0",
        "@livekit/react-native-webrtc": "144.1.2",
      },
    }),
  );
  await writeFile(
    join(root, "apps/mobile/app.json"),
    JSON.stringify({
      expo: {
        plugins: [
          "expo-router",
          ["expo-build-properties", { ios: { enableSceneSupport: true } }],
          "expo-audio",
        ],
      },
    }),
  );
  return root;
}

function expoConfig(overrides: Record<string, unknown> = {}) {
  return {
    name: "divineruin",
    plugins: [
      "expo-router",
      ["expo-build-properties", { ios: { enableSceneSupport: true } }],
      "expo-audio",
    ],
    ...overrides,
  };
}

function eslintConfig(): Array<Record<string, unknown>> {
  return [
    {
      languageOptions: {
        parserOptions: { projectService: { allowDefaultProject: ["eslint.config.js"] } },
      },
    },
    {
      files: ["apps/mobile/src/components/hud/panel-shell.tsx"],
      rules: { "react-hooks/immutability": "off" },
    },
  ];
}

async function verify(
  root: string,
  expo: unknown = expoConfig(),
  eslint: unknown[] = eslintConfig(),
) {
  return verifySdk57Baseline({
    repoRoot: root,
    loadExpoConfig: () => Promise.resolve(expo),
    loadEslintConfig: () => Promise.resolve(eslint),
  });
}

async function failure(action: Promise<unknown>): Promise<string> {
  try {
    await action;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
  throw new Error("expected failure");
}

describe("verifySdk57Baseline", () => {
  test("accepts an SDK 57 project with the permanent config floors", async () => {
    await verify(await fixture());
  });

  test("rejects Expo 56", async () => {
    const root = await fixture();
    await writeFile(
      join(root, "apps/mobile/package.json"),
      JSON.stringify({ dependencies: { expo: "56.0.22" } }),
    );
    expect(await failure(verify(root))).toMatch(/Expo SDK 57/);
  });

  test.each([
    ["expo-constants", "56.0.26"],
    ["react-native-screens", "4.26.0"],
    ["hermes-compiler", "0.15.0"],
  ])("rejects the temporary root override %s", async (name, version) => {
    const root = await fixture();
    await writeFile(
      join(root, "package.json"),
      JSON.stringify({ overrides: { "dnssd-advertise": "1.1.4", [name]: version } }),
    );
    expect(await failure(verify(root))).toContain(name);
  });

  test("requires the permanent override corpus floor", async () => {
    const root = await fixture();
    await writeFile(join(root, "package.json"), JSON.stringify({ overrides: {} }));
    expect(await failure(verify(root))).toContain("dnssd-advertise");
  });

  test("rejects a root LiveKit override", async () => {
    const root = await fixture();
    await writeFile(
      join(root, "package.json"),
      JSON.stringify({
        overrides: { "dnssd-advertise": "1.1.4", "@livekit/react-native": "3.0.0" },
      }),
    );
    expect(await failure(verify(root))).toMatch(/LiveKit root override/);
  });

  test.each([
    ["@livekit/react-native", "3.0.0"],
    ["@livekit/react-native-webrtc", "144.2.0"],
  ])("rejects incompatible native dependency %s@%s", async (name, version) => {
    const root = await fixture();
    const path = join(root, "apps/mobile/package.json");
    const manifest = (await Bun.file(path).json()) as {
      dependencies: Record<string, string>;
    };
    manifest.dependencies[name] = version;
    await writeFile(path, JSON.stringify(manifest));
    expect(await failure(verify(root))).toContain(`${name}@${version}`);
  });

  test("rejects a mobile Babel config", async () => {
    const root = await fixture();
    await writeFile(join(root, "apps/mobile/babel.config.js"), "module.exports = {};\n");
    expect(await failure(verify(root))).toMatch(/babel\.config\.js/);
  });

  test.each([
    ["useHermesV1", { useHermesV1: false }],
    ["buildReactNativeFromSource", { buildReactNativeFromSource: true }],
  ])("rejects evaluated SDK 56 config: %s", async (expected, mutation) => {
    const root = await fixture();
    expect(await failure(verify(root, expoConfig(mutation)))).toContain(expected);
  });

  test("requires the Xcode 27 scene opt-in in both authored and evaluated config", async () => {
    const root = await fixture();
    expect(
      await failure(verify(root, expoConfig({ plugins: ["expo-router", "expo-audio"] }))),
    ).toMatch(/scene support/);
    await writeFile(
      join(root, "apps/mobile/app.json"),
      JSON.stringify({ expo: { plugins: ["expo-router", "expo-audio"] } }),
    );
    expect(await failure(verify(root))).toMatch(/scene support/);
    await writeFile(
      join(root, "apps/mobile/app.json"),
      JSON.stringify({
        expo: {
          plugins: [
            "expo-router",
            ["expo-build-properties", { ios: { enableSceneSupport: false } }],
          ],
        },
      }),
    );
    expect(await failure(verify(root))).toMatch(/scene support/);
  });

  test("requires a reachable nonempty evaluated Expo plugin corpus", async () => {
    const root = await fixture();
    expect(await failure(verify(root, { name: "divineruin", plugins: [] }))).toMatch(
      /plugin corpus/,
    );
  });

  test("requires evaluated Expo config to be reachable", async () => {
    const root = await fixture();
    expect(
      await failure(
        verifySdk57Baseline({
          repoRoot: root,
          loadExpoConfig: () => Promise.reject(new Error("expo config crashed")),
          loadEslintConfig: () => Promise.resolve(eslintConfig()),
        }),
      ),
    ).toMatch(/expo config crashed/);
  });

  test("rejects Babel-specific evaluated ESLint config", async () => {
    const root = await fixture();
    const config = eslintConfig();
    config.push({ files: ["apps/mobile/babel.config.js"], rules: {} });
    expect(await failure(verify(root, expoConfig(), config))).toMatch(/Babel-specific ESLint/);
  });

  test("requires the evaluated ESLint allowDefaultProject floor", async () => {
    const root = await fixture();
    const config = eslintConfig();
    config[0] = { languageOptions: { parserOptions: { projectService: {} } } };
    expect(await failure(verify(root, expoConfig(), config))).toMatch(/allowDefaultProject/);
  });

  test("requires the evaluated Reanimated rule floor", async () => {
    const root = await fixture();
    expect(await failure(verify(root, expoConfig(), [eslintConfig()[0]]))).toMatch(/Reanimated/);
  });

  test("requires evaluated ESLint config to be reachable and nonempty", async () => {
    const root = await fixture();
    expect(await failure(verify(root, expoConfig(), []))).toMatch(/ESLint config corpus/);
  });
});
