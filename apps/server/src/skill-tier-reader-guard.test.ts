import { expect, test } from "bun:test";

type SourceFile = { path: string; source: string };

function skillAdvancementReaders(files: SourceFile[]): string[] {
  return files.flatMap(({ path, source }) =>
    Array.from(source.matchAll(/\bskill_advancement\b/gi), () => path),
  );
}

test("the server has no unreviewed skill-advancement tier reader", async () => {
  const glob = new Bun.Glob("**/*.ts");
  const files: SourceFile[] = [];
  for await (const path of glob.scan({ cwd: import.meta.dir })) {
    if (path.endsWith(".test.ts")) continue;
    files.push({ path, source: await Bun.file(`${import.meta.dir}/${path}`).text() });
  }

  expect(files.length).toBeGreaterThan(0);
  expect(skillAdvancementReaders(files)).toEqual(["activity_create.ts"]);
});

test("the server skill-reader guard detects a new raw table reader", () => {
  const scratch = [
    {
      path: "scratch.ts",
      source: "SELECT tier FROM skill_advancement WHERE skill_id = 'crafting'",
    },
  ];

  expect(skillAdvancementReaders(scratch)).toEqual(["scratch.ts"]);
});
