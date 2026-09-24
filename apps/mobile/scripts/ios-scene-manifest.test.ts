import { afterAll, expect, test } from "bun:test";
import plist from "@expo/plist";
import { cp, mkdtemp, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

const repoRoot = join(import.meta.dir, "../../..");
const temp = await mkdtemp(join(tmpdir(), "divineruin-prebuild-"));
afterAll(() => rm(temp, { recursive: true, force: true }));

async function prebuildIos(): Promise<string> {
  const mobileRoot = join(temp, "apps/mobile");
  await cp(join(repoRoot, "apps/mobile"), mobileRoot, {
    recursive: true,
    filter: (source) => !["node_modules", "ios", "android"].includes(basename(source)),
  });
  await symlink(join(repoRoot, "node_modules"), join(temp, "node_modules"));
  const child = Bun.spawn(["bun", "expo", "prebuild", "--platform", "ios", "--no-install"], {
    cwd: mobileRoot,
    env: { ...process.env, CI: "1", EXPO_NO_TELEMETRY: "1" },
    stdout: "ignore",
    stderr: "pipe",
  });
  const [stderr, exit] = await Promise.all([new Response(child.stderr).text(), child.exited]);
  if (exit !== 0) throw new Error(`expo prebuild failed: ${stderr.trim()}`);
  return join(mobileRoot, "ios");
}

// iOS 27 halts at launch unless the app adopts the UIScene life cycle.
test("prebuilt iOS project declares Expo's scene delegate", async () => {
  const ios = await prebuildIos();
  const info = plist.parse(await readFile(join(ios, "divineruin/Info.plist"), "utf8")) as Record<
    string,
    unknown
  >;
  expect(info.UIApplicationSceneManifest).toEqual({
    UIApplicationSupportsMultipleScenes: false,
    UISceneConfigurations: {
      UIWindowSceneSessionRoleApplication: [
        {
          UISceneConfigurationName: "Default Configuration",
          UISceneDelegateClassName: "EXExpoAppSceneDelegate",
        },
      ],
    },
  });
  expect(await readFile(join(ios, "divineruin/AppDelegate.swift"), "utf8")).toContain(
    "class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {",
  );
}, 120_000);
