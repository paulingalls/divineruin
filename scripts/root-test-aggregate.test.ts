import { expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const REPO_ROOT = resolve(import.meta.dir, "..");

test.each(["packages/design-tokens", "e2e"])(
  "the root aggregate includes %s failures",
  async (faultDirectory) => {
    const root = await mkdtemp(join(tmpdir(), "root-test-aggregate-"));
    try {
      const source = (await Bun.file(join(REPO_ROOT, "package.json")).json()) as {
        scripts: Record<string, string>;
      };
      await writeFile(
        join(root, "package.json"),
        JSON.stringify({
          private: true,
          scripts: { test: source.scripts.test, "test:server": "bun -e 'process.exit(0)'" },
        }),
      );
      for (const directory of [
        "scripts",
        "packages/shared",
        "packages/design-tokens",
        "apps/mobile",
        "apps/web",
        "e2e",
      ]) {
        await mkdir(join(root, directory), { recursive: true });
        await writeFile(
          join(root, directory, "pass.test.ts"),
          'import { test } from "bun:test"; test("pass", () => {});\n',
        );
      }
      await writeFile(
        join(
          root,
          faultDirectory,
          faultDirectory === "e2e" ? "require-environment.test.ts" : "fault.test.ts",
        ),
        'import { expect, test } from "bun:test"; test("fault", () => expect(true).toBe(false));\n',
      );

      const child = Bun.spawn(["bun", "run", "test"], {
        cwd: root,
        stdout: "pipe",
        stderr: "pipe",
      });
      const [stderr, exitCode] = await Promise.all([
        new Response(child.stderr).text(),
        child.exited,
      ]);
      expect(exitCode).not.toBe(0);
      expect(stderr).toContain(
        faultDirectory === "e2e" ? "require-environment.test.ts" : "fault.test.ts",
      );
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  },
);
