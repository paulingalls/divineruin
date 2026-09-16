#!/usr/bin/env bun
/**
 * Batch image generation CLI.
 *
 * Usage:
 *   bun run scripts/generate_art.ts --template <id> --vars '{"key":"value"}'
 *   bun run scripts/generate_art.ts --batch mvp
 */

import { generateImage, computeAssetId, getAssetPath } from "../apps/server/src/image-gen.ts";
import { PROMPT_TEMPLATES } from "../apps/server/src/image-prompt-templates.ts";
import { MVP_BATCH } from "./art/mvp-batch.ts";

async function runSingle(templateId: string, varsJson: string) {
  const template = PROMPT_TEMPLATES[templateId];
  if (!template) {
    console.error(`Unknown template: ${templateId}`);
    console.error(`Available: ${Object.keys(PROMPT_TEMPLATES).join(", ")}`);
    process.exit(1);
  }

  let vars: Record<string, string>;
  try {
    vars = JSON.parse(varsJson) as Record<string, string>;
  } catch {
    console.error("Invalid JSON for --vars");
    process.exit(1);
  }

  console.log(`Generating ${templateId}...`);
  const start = performance.now();
  const result = await generateImage(templateId, vars);
  const elapsed = ((performance.now() - start) / 1000).toFixed(1);
  console.log(`Done: ${result.assetId} (${elapsed}s)`);
  console.log(`File: ${result.path}`);
}

async function runBatch(batchName: string) {
  if (batchName !== "mvp") {
    console.error(`Unknown batch: ${batchName}. Available: mvp`);
    process.exit(1);
  }

  const total = MVP_BATCH.length;
  let generated = 0;
  let skipped = 0;
  const batchStart = performance.now();

  console.log(`\nGenerating ${total} MVP assets...\n`);

  for (let i = 0; i < total; i++) {
    const entry = MVP_BATCH[i]!;
    const prefix = `[${i + 1}/${total}]`;

    // Check for dedup before calling (to show skip message)
    process.stdout.write(`${prefix} Generating ${entry.templateId} (${entry.label})... `);

    const start = performance.now();
    try {
      const result = await generateImage(entry.templateId, entry.vars, entry.assetId ? { assetId: entry.assetId } : undefined);
      const elapsed = ((performance.now() - start) / 1000).toFixed(1);

      // If it completed in under 500ms, it was likely a cache hit
      if (performance.now() - start < 500) {
        console.log(`skipped (cached: ${result.assetId})`);
        skipped++;
      } else {
        console.log(`done (${result.assetId}) ${elapsed}s`);
        generated++;
      }
    } catch (err) {
      const elapsed = ((performance.now() - start) / 1000).toFixed(1);
      console.log(`FAILED ${elapsed}s`);
      console.error(`  Error: ${err instanceof Error ? err.message : String(err)}`);
    }

    // Rate limit delay between API calls (skip for cached results)
    if (i < total - 1 && performance.now() - start > 500) {
      await Bun.sleep(2000);
    }
  }

  const totalElapsed = ((performance.now() - batchStart) / 1000).toFixed(1);
  console.log(`\n--- Summary ---`);
  console.log(`Generated: ${generated}`);
  console.log(`Skipped (cached): ${skipped}`);
  console.log(`Failed: ${total - generated - skipped}`);
  console.log(`Total time: ${totalElapsed}s`);
  console.log(`Est. cost: ~$${(generated * 0.04).toFixed(2)} (at ~$0.04/image)`);

  // Copy assets to mobile bundle directories
  const mobileBase = `${import.meta.dir}/../apps/mobile/assets/images`;
  await copyBatchAssets("locationId", `${mobileBase}/locations`, "location");
  await copyBatchAssets("marketingId", `${mobileBase}/marketing`, "marketing");
}

async function copyBatchAssets(
  filterKey: "locationId" | "marketingId",
  destDir: string,
  label: string,
) {
  await Bun.$`mkdir -p ${destDir}`;

  const entries = MVP_BATCH.filter((e) => e[filterKey]);
  let copied = 0;

  console.log(`\nCopying ${entries.length} ${label} assets to mobile bundle...`);

  for (const entry of entries) {
    const assetId = entry.assetId ?? computeAssetId(entry.templateId, entry.vars);
    const srcPath = getAssetPath(assetId);
    const destName = entry[filterKey]!;
    const dest = `${destDir}/${destName}.png`;
    const src = Bun.file(srcPath);
    if (await src.exists()) {
      await Bun.write(dest, src);
      copied++;
    } else {
      console.warn(`  Warning: source not found for ${destName} (${srcPath})`);
    }
  }

  console.log(`Copied ${copied}/${entries.length} ${label} assets.`);
}

// Parse CLI args
const args = process.argv.slice(2);
const flagIndex = (flag: string) => args.indexOf(flag);

if (flagIndex("--batch") !== -1) {
  const batchName = args[flagIndex("--batch") + 1];
  if (!batchName) {
    console.error("Usage: --batch <name>");
    process.exit(1);
  }
  await runBatch(batchName);
} else if (flagIndex("--template") !== -1) {
  const templateId = args[flagIndex("--template") + 1];
  const varsIdx = flagIndex("--vars");
  const varsJson = varsIdx !== -1 ? args[varsIdx + 1] ?? "{}" : "{}";
  if (!templateId) {
    console.error("Usage: --template <id> [--vars '{...}']");
    process.exit(1);
  }
  await runSingle(templateId, varsJson);
} else {
  console.log("Image generation CLI for Divine Ruin");
  console.log("");
  console.log("Usage:");
  console.log("  bun run scripts/generate_art.ts --template <id> [--vars '{...}']");
  console.log("  bun run scripts/generate_art.ts --batch mvp");
  console.log("");
  console.log(`Templates: ${Object.keys(PROMPT_TEMPLATES).join(", ")}`);
}
