import { test, expect } from "bun:test";
import { SHIP_FACES } from "@divineruin/design-tokens";
import { subsetJobs, FONT_SUBSET_UNICODES } from "./gen-fonts.ts";

// gen-fonts.ts subsets the shipped faces from the @expo-google-fonts TTFs in
// node_modules into src/fonts/*.woff2. It derives the face set from the shared
// SHIP_FACES manifest (same source gen-fonts-css.ts and gen-theme.ts read), so
// the subset list can never drift from what fonts.css declares. The woff2 are
// committed binaries; this script only re-subsets on a deliberate author re-run,
// so the tests pin the job derivation, not the woff2 output.

test("derives one subset job per shipped face, outputs == the manifest files", () => {
  const jobs = subsetJobs();
  expect(jobs).toHaveLength(SHIP_FACES.length);
  expect(jobs.map((j) => j.out).sort()).toEqual(SHIP_FACES.map((f) => f.file).sort());
});

test("each job resolves to an installed source TTF (script would find its inputs)", () => {
  for (const job of subsetJobs()) {
    expect(Bun.file(job.source).size).toBeGreaterThan(0);
  }
});

test("maps weight and style to the expo-google-fonts TTF variant", () => {
  const jobs = subsetJobs();
  const sourceFor = (out: string) => jobs.find((j) => j.out === out)?.source ?? "";
  expect(sourceFor("cormorant-garamond-300.woff2")).toContain(
    "/300Light/CormorantGaramond_300Light.ttf",
  );
  expect(sourceFor("cormorant-garamond-400-italic.woff2")).toContain(
    "/400Regular_Italic/CormorantGaramond_400Regular_Italic.ttf",
  );
  expect(sourceFor("ibm-plex-mono-400.woff2")).toContain("/400Regular/IBMPlexMono_400Regular.ttf");
});

test("preserves the Google Fonts latin subset range", () => {
  expect(FONT_SUBSET_UNICODES).toBe("U+0000-00FF,U+0131,U+0152-0153,U+2018-201F,U+2026,U+2122");
});
