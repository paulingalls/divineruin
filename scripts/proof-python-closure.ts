import { closure } from "../node_modules/@pi-innovations/proof/src/imports";
import { pythonClosure } from "../node_modules/@pi-innovations/proof/src/python";

const { paths, launches } = (await Bun.stdin.json()) as { paths: string[]; launches: string[] };
const roots = ["apps/agent", "apps/agent/tests", "scripts"];
const texts = new Map<string, string>();
const inGit = Bun.spawnSync(["git", "rev-parse", "--is-inside-work-tree"]);
let available: string[];
if (inGit.exitCode === 0 && inGit.stdout.toString().trim() === "true") {
  const listed = Bun.spawnSync([
    "git",
    "ls-files",
    "-z",
    "--cached",
    "--others",
    "--exclude-standard",
  ]);
  if (listed.exitCode !== 0) throw new Error(`git ls-files failed: ${listed.stderr.toString()}`);
  available = [];
  for (const path of listed.stdout.toString().split("\0").filter(Boolean)) {
    if (await Bun.file(path).exists()) available.push(path);
  }
} else {
  // Proof sandboxes contain the tracked tree without Git metadata.
  available = [...new Bun.Glob("**/*").scanSync({ dot: true })].filter(
    (path) => !path.split("/").some((part) => ["node_modules", ".git", ".venv"].includes(part)),
  );
}
for (const path of available) texts.set(path, await Bun.file(path).text());
const source = {
  paths: available,
  read: (path: string) => texts.get(path),
  mode: (path: string) => (texts.has(path) ? "100644" : undefined),
};
const result = Object.fromEntries(
  paths.map((entry) => {
    const closure = pythonClosure(entry, source, roots);
    // Isolate unresolved imports in this file from reasons in its dependencies.
    const local = pythonClosure(
      entry,
      {
        ...source,
        read: (path: string) => (path === entry ? texts.get(path) : ""),
      },
      roots,
    );
    return [
      entry,
      {
        closure: [...closure.paths].sort(),
        direct: [...local.paths].sort(),
        reason: closure.reason,
        localReason: local.reason,
      },
    ];
  }),
);
const runtime = Object.fromEntries(
  launches.map((entry) => {
    const found = closure(entry, source);
    if (found.reason) throw new Error(`${entry}: ${found.reason}`);
    return [entry, [...found.paths].sort()];
  }),
);
await Bun.write(Bun.stdout, JSON.stringify({ graph: result, runtime }));
