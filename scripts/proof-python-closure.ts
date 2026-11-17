import { pythonClosure } from "../node_modules/@pi-innovations/proof/src/python";

const paths = (await Bun.stdin.json()) as string[];
const roots = ["apps/agent", "apps/agent/tests", "scripts"];
const texts = new Map<string, string>();
for (const path of paths) texts.set(path, await Bun.file(path).text());
const source = {
  paths,
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
await Bun.write(Bun.stdout, JSON.stringify(result));
