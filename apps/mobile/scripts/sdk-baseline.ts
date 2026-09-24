import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export interface SdkBaselineOptions {
  repoRoot: string;
  loadExpoConfig?: (mobileRoot: string) => Promise<unknown>;
  loadEslintConfig?: (repoRoot: string) => Promise<unknown[]>;
}

const REMOVED_OVERRIDES = ["expo-constants", "react-native-screens", "hermes-compiler"];
const LIVEKIT_NATIVE_GRAPH = {
  "@livekit/react-native": "2.12.0",
  "@livekit/react-native-webrtc": "144.1.2",
};

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function contains(value: unknown, predicate: (key: string, value: unknown) => boolean): boolean {
  if (predicate("", value)) return true;
  if (Array.isArray(value)) return value.some((item) => contains(item, predicate));
  const current = record(value);
  return Object.entries(current).some(
    ([key, child]) => predicate(key, child) || contains(child, predicate),
  );
}

async function json(path: string): Promise<Record<string, unknown>> {
  return record(JSON.parse(await readFile(path, "utf8")));
}

async function loadExpoConfig(mobileRoot: string): Promise<unknown> {
  const child = Bun.spawn(["bun", "expo", "config", "--json"], {
    cwd: mobileRoot,
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr, exit] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (exit !== 0) throw new Error(`Expo config evaluation failed: ${stderr.trim()}`);
  return JSON.parse(stdout);
}

async function loadEslintConfig(repoRoot: string): Promise<unknown[]> {
  const url = pathToFileURL(join(repoRoot, "eslint.config.js"));
  url.searchParams.set("sdkBaseline", String(Date.now()));
  const evaluated = (await import(url.href)) as { default?: unknown };
  if (!Array.isArray(evaluated.default)) throw new Error("evaluated ESLint config is not an array");
  return evaluated.default.flat(Number.POSITIVE_INFINITY) as unknown[];
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function hasSceneSupport(plugins: unknown[]): boolean {
  return plugins.some(
    (entry) =>
      Array.isArray(entry) &&
      entry[0] === "expo-build-properties" &&
      record(record(entry[1]).ios).enableSceneSupport === true,
  );
}

function verifyEslint(configs: unknown[]): void {
  if (configs.length === 0) throw new Error("evaluated ESLint config corpus is empty");
  const entries = configs.map(record);
  const hasBabelEntry = entries.some((entry) =>
    stringArray(entry.files).includes("apps/mobile/babel.config.js"),
  );
  if (hasBabelEntry) throw new Error("Babel-specific ESLint config remains");

  const allowDefaultProject = entries.flatMap((entry) => {
    const language = record(entry.languageOptions);
    const parser = record(language.parserOptions);
    const service = record(parser.projectService);
    return stringArray(service.allowDefaultProject);
  });
  if (!allowDefaultProject.includes("eslint.config.js")) {
    throw new Error("evaluated ESLint allowDefaultProject floor is missing eslint.config.js");
  }
  if (allowDefaultProject.includes("apps/mobile/babel.config.js")) {
    throw new Error("Babel-specific ESLint allowDefaultProject entry remains");
  }

  const hasReanimatedFloor = entries.some((entry) => {
    const files = stringArray(entry.files);
    const rules = record(entry.rules);
    return (
      files.includes("apps/mobile/src/components/hud/panel-shell.tsx") &&
      rules["react-hooks/immutability"] === "off"
    );
  });
  if (!hasReanimatedFloor) throw new Error("evaluated Reanimated ESLint rule floor is missing");
}

export async function verifySdk57Baseline(options: SdkBaselineOptions): Promise<void> {
  const mobileRoot = join(options.repoRoot, "apps/mobile");
  const [rootManifest, mobileManifest, appConfig] = await Promise.all([
    json(join(options.repoRoot, "package.json")),
    json(join(mobileRoot, "package.json")),
    json(join(mobileRoot, "app.json")),
  ]);
  const dependencies = record(mobileManifest.dependencies);
  if (typeof dependencies.expo !== "string" || !/^57\./.test(dependencies.expo)) {
    throw new Error("mobile manifest must target Expo SDK 57");
  }

  const overrides = record(rootManifest.overrides);
  if (!overrides["dnssd-advertise"])
    throw new Error("dnssd-advertise override corpus floor is missing");
  for (const name of REMOVED_OVERRIDES) {
    if (overrides[name]) throw new Error(`temporary SDK 56 root override remains: ${name}`);
  }
  if (overrides["@livekit/react-native"])
    throw new Error("unauthorized LiveKit root override remains");
  for (const [name, expected] of Object.entries(LIVEKIT_NATIVE_GRAPH)) {
    if (dependencies[name] !== expected) {
      throw new Error(`incompatible native dependency ${name}@${String(dependencies[name])}`);
    }
  }

  const babelPath = join(mobileRoot, "babel.config.js");
  if (await stat(babelPath).catch(() => null))
    throw new Error("apps/mobile/babel.config.js remains");

  const directPlugins = record(appConfig.expo).plugins;
  if (!Array.isArray(directPlugins) || directPlugins.length === 0) {
    throw new Error("mobile app plugin corpus is empty");
  }
  const evaluated = await (options.loadExpoConfig ?? loadExpoConfig)(mobileRoot);
  const evaluatedPlugins = record(evaluated).plugins;
  if (!Array.isArray(evaluatedPlugins) || evaluatedPlugins.length === 0) {
    throw new Error("evaluated Expo plugin corpus is empty");
  }
  if (contains(evaluated, (key, value) => key === "useHermesV1" && value === false)) {
    throw new Error("evaluated Expo config retains useHermesV1=false");
  }
  if (contains(evaluated, (key, value) => key === "buildReactNativeFromSource" && value === true)) {
    throw new Error("evaluated Expo config retains buildReactNativeFromSource=true");
  }
  if (
    typeof dependencies["expo-build-properties"] !== "string" ||
    !hasSceneSupport(directPlugins) ||
    !hasSceneSupport(evaluatedPlugins)
  )
    throw new Error("Expo SDK 57 requires scene support in authored and evaluated config");

  const eslint = await (options.loadEslintConfig ?? loadEslintConfig)(options.repoRoot);
  verifyEslint(eslint);
}
