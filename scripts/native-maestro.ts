import { access, cp, mkdir, readdir } from "node:fs/promises";
import { constants } from "node:fs";
import { homedir } from "node:os";
import { basename, join, resolve } from "node:path";
import {
  withOwnedProcesses,
  type OwnedProcesses,
} from "../apps/mobile/scripts/native-transport-processes";
import { runNativeBuild } from "../apps/mobile/scripts/verify-native-build";
import { createProofNativeBuildDeps } from "../apps/mobile/scripts/verify-native-build-runtime";
import { runScenario } from "../apps/mobile/scripts/verify-native-transport";
import { choirScenario } from "../apps/mobile/scripts/verify-choir-encounter";
import {
  withNativeOwnedBackend,
  withPatronProbe,
} from "../apps/mobile/scripts/verify-patron-abilities";
import { createInventoryProxy } from "../apps/mobile/scripts/verify-http-inventory";
import { runPreparedLiveMaterial } from "../apps/mobile/scripts/verify-live-material-inventory";

const flows = [
  "launch.yaml",
  "auth-form.yaml",
  "native-transport.yaml",
  "choir-encounter.yaml",
  "patron-abilities.yaml",
  "iron-resolve-hud.yaml",
  "http-inventory-refresh.yaml",
  "http-inventory-resume.yaml",
  "live-material-inventory.yaml",
] as const;

type Flow = (typeof flows)[number];

async function resolveMaestro() {
  const fallback = join(homedir(), ".maestro/bin/maestro");
  const executable = Bun.which("maestro") ?? fallback;
  await access(executable, constants.X_OK).catch((cause: unknown) => {
    throw new Error(`Maestro CLI unavailable in PATH or at ${fallback}`, { cause });
  });
  return executable;
}

function providerEnvironment() {
  const source = process.env;
  const names = [
    "PROOF_NATIVE_CLONE",
    "PROOF_NATIVE_ARTIFACTS",
    "DATABASE_URL",
    "REDIS_URL",
    "PROOF_AGENT_PROVIDER",
    "PROOF_ACCEPTANCE_ADMIN",
    "PROOF_ACCEPTANCE_TEMPLATE",
    "PROOF_ACCEPTANCE_REDIS",
    "PROOF_ACCEPTANCE_REDIS_DATABASES",
    "PROOF_LIVEKIT_WS",
    "PROOF_LIVEKIT_HTTP",
    "PROOF_LIVEKIT_KEY",
    "PROOF_LIVEKIT_SECRET",
  ] as const;
  const endpoints = Object.fromEntries(
    names.map((name) => {
      const value = source[name]?.trim();
      if (!value) throw new Error(`Native stack provider must supply ${name}`);
      return [name, value];
    }),
  ) as Record<(typeof names)[number], string>;
  for (const url of [endpoints.DATABASE_URL, endpoints.REDIS_URL, endpoints.PROOF_LIVEKIT_WS]) {
    const endpoint = new URL(url);
    if (endpoint.hostname !== "127.0.0.1" || !endpoint.port)
      throw new Error("Native stack provider must supply explicit loopback endpoints");
  }
  return endpoints;
}

async function requirePassingReport(
  scope: OwnedProcesses,
  root: string,
  report: string,
  flow: string,
) {
  const child = scope.spawn(
    [
      "python3",
      "-c",
      `
import sys
from xml.etree import ElementTree
path, name = sys.argv[1:]
root = ElementTree.parse(path).getroot()
suites = [root] if root.tag == "testsuite" else root.findall("./testsuite")
cases = [case for suite in suites for case in suite.findall("./testcase")]
if len(cases) != 1 or cases[0].get("name") != name:
    raise SystemExit(f"{path}: expected one testcase named {name}")
if cases[0].get("status") != "SUCCESS" or any(
    node.tag in ("failure", "error", "skipped") for node in root.iter()
):
    raise SystemExit(f"{path}: expected a passing testcase")
`,
      report,
      basename(flow, ".yaml"),
    ],
    { cwd: root },
  );
  if ((await scope.wait(child.exited)) !== 0)
    throw new Error(`Maestro flow ${flow} has no passing JUnit report: ${report}`);
}

async function runJourneys(
  scope: OwnedProcesses,
  root: string,
  results: string,
  executable: string,
  environment: Record<string, string>,
  proxy: ReturnType<typeof createInventoryProxy>,
  status: Map<Flow, "PASS" | "FAIL">,
) {
  const launchUrl = environment.MAESTRO_APP_LAUNCH_URL;
  const udid = environment.IOS_SIMULATOR_UDID;
  const databaseUrl = environment.DATABASE_URL;
  if (!launchUrl || !udid || !databaseUrl)
    throw new Error("Prepared native session did not supply launch, simulator and database");
  const report = (flow: string) => join(results, `${flow}.xml`);
  const spawnMaestro = (flow: string, output: string, variables: Record<string, string>) =>
    scope.spawn(
      [
        executable,
        `--device=${udid}`,
        "test",
        "--format",
        "junit",
        "--output",
        report(flow),
        `--test-output-dir=${output}`,
        ...Object.entries({ APP_LAUNCH_URL: launchUrl, ...variables }).flatMap(([key, value]) => [
          "-e",
          `${key}=${value}`,
        ]),
        join(root, "apps/mobile/.maestro", flow),
      ],
      { cwd: root, env: environment },
    );
  const maestro = async (flow: Flow, variables: Record<string, string> = {}) => {
    const child = spawnMaestro(flow, join(results, flow), variables);
    if ((await scope.wait(child.exited)) !== 0) throw new Error(`Maestro failed: ${flow}`);
  };
  const journey = async (flow: Flow, run = () => maestro(flow)) => {
    status.set(flow, "FAIL");
    await run();
    await requirePassingReport(scope, root, report(flow), flow);
    status.set(flow, "PASS");
  };
  const flowDir = join(root, "apps/mobile/.maestro");
  const files = (await readdir(flowDir)).filter((name) => name.endsWith(".yaml")).sort();
  if (JSON.stringify(files) !== JSON.stringify([...flows].sort()))
    throw new Error(`Native Maestro journey list differs from ${flowDir}: ${files.join(", ")}`);

  await journey("launch.yaml");
  await journey("auth-form.yaml");
  const prepared = { launchUrl, spawnMaestro, results };
  await journey("native-transport.yaml", () =>
    runScenario(scope, root, environment, udid, "none", {}, prepared),
  );
  await journey("choir-encounter.yaml", () =>
    runScenario(scope, root, environment, udid, "none", choirScenario, prepared),
  );
  await journey("patron-abilities.yaml", () =>
    withPatronProbe(scope, root, environment, join(results, "patron-probe"), (route) =>
      maestro("patron-abilities.yaml", { PATRON_ROUTE: route }),
    ),
  );
  await journey("iron-resolve-hud.yaml");
  await proxy.run(scope, databaseUrl, (file, route, after) => {
    if (file !== "http-inventory-refresh.yaml" && file !== "http-inventory-resume.yaml")
      throw new Error(`Unexpected native HTTP inventory flow: ${file}`);
    return journey(file, async () => {
      await maestro(file, { ROUTE_URL: route });
      await after();
    });
  });
  await journey("live-material-inventory.yaml", () =>
    runPreparedLiveMaterial(scope, results, environment, (variables) =>
      maestro("live-material-inventory.yaml", variables),
    ),
  );
  if (status.size !== flows.length || [...status.values()].some((result) => result !== "PASS"))
    throw new Error("Native Maestro finished without a passing report for every flow");
}

async function runNativeMaestro() {
  const status = new Map<Flow, "PASS" | "FAIL">();
  try {
    const provider = providerEnvironment();
    const executable = await resolveMaestro();
    const root = resolve(import.meta.dir, "..");
    const results = join(root, "test-results/native-maestro");
    await mkdir(results, { recursive: true });
    const environment = {
      ...Object.fromEntries(
        Object.entries(process.env).filter(
          (entry): entry is [string, string] => entry[1] !== undefined,
        ),
      ),
      ...provider,
      LIVEKIT_URL: provider.PROOF_LIVEKIT_WS,
      LIVEKIT_API_KEY: provider.PROOF_LIVEKIT_KEY,
      LIVEKIT_API_SECRET: provider.PROOF_LIVEKIT_SECRET,
      // CocoaPods needs a UTF-8 locale in Proof and launchd’s minimal environments.
      LC_ALL: "en_US.UTF-8",
      ALLOW_PAID_TESTS: "",
      REQUIRE_REAL_LLM: "",
    };
    try {
      await withOwnedProcesses(async (scope) => {
        const deps = createProofNativeBuildDeps(root, scope, provider.PROOF_NATIVE_CLONE);
        await withNativeOwnedBackend(scope, root, environment, results, async (backend) => {
          const proxy = createInventoryProxy(backend.EXPO_PUBLIC_API_URL);
          try {
            console.log(
              `Native provider: API ${proxy.origin}, Postgres port ${new URL(provider.DATABASE_URL).port}, ` +
                `Valkey port ${new URL(provider.REDIS_URL).port}, LiveKit ${provider.PROOF_LIVEKIT_WS}`,
            );
            await runNativeBuild({
              repoRoot: root,
              processEnv: {
                ...backend,
                EXPO_PUBLIC_API_URL: proxy.origin,
              },
              deps,
              prepared: (env) =>
                runJourneys(
                  scope,
                  root,
                  results,
                  executable,
                  Object.fromEntries(
                    Object.entries(env).filter(
                      (entry): entry is [string, string] => entry[1] !== undefined,
                    ),
                  ),
                  proxy,
                  status,
                ),
            });
          } finally {
            await proxy.stop();
          }
        });
      });
    } finally {
      await mkdir(provider.PROOF_NATIVE_ARTIFACTS, { recursive: true });
      await cp(results, provider.PROOF_NATIVE_ARTIFACTS, { recursive: true });
      console.log(`Native Maestro artifacts: ${provider.PROOF_NATIVE_ARTIFACTS}`);
    }
  } finally {
    for (const flow of flows)
      console.log(`native-maestro: ${flow} ${status.get(flow) ?? "NOT RUN"}`);
  }
}

if (import.meta.main) await runNativeMaestro();
