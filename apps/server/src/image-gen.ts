import { logError } from "./env.ts";
import { sql } from "./db.ts";
import { resolvePrompt } from "./image-prompt-templates.ts";
import { postProcessImage } from "./image-post-process.ts";
import { findAssetPath } from "./image-dir.ts";
import { requestImage } from "./image-provider.ts";

export function computeAssetId(templateId: string, vars: Record<string, string>): string {
  const sortedEntries = Object.entries(vars).sort(([a], [b]) => a.localeCompare(b));
  const payload = templateId + JSON.stringify(sortedEntries);
  const hash = new Bun.CryptoHasher("sha256").update(payload).digest("hex").slice(0, 16);
  return `img_${hash}`;
}

export function getAssetPath(assetId: string, directory: string): string {
  return `${directory}/${assetId}.png`;
}

/**
 * Generate an image from a prompt template. Deduplicates by content-addressable ID.
 * Returns the asset ID and file path.
 */
export async function generateImage(
  templateId: string,
  vars: Record<string, string>,
  directory: string,
  options?: { assetId?: string },
): Promise<{ assetId: string; path: string }> {
  if (options?.assetId && !/^[a-zA-Z0-9_]+$/.test(options.assetId)) {
    throw new Error(`Invalid assetId: ${options.assetId}`);
  }
  const assetId = options?.assetId ?? computeAssetId(templateId, vars);
  const cached = await findAssetPath(assetId);
  if (cached) return { assetId, path: cached };
  const path = getAssetPath(assetId, directory);

  const { prompt, template } = resolvePrompt(templateId, vars);

  const rawBuffer = await requestImage(prompt, templateId);

  const processed = await postProcessImage(rawBuffer, {
    aspectRatio: template.aspectRatio,
  });

  const dir = path.substring(0, path.lastIndexOf("/"));
  await Bun.write(dir + "/.keep", "");

  await Bun.write(path, processed);

  try {
    await sql`
      INSERT INTO generated_assets (id, template_id, variables, file_path, aspect_ratio, category)
      VALUES (${assetId}, ${templateId}, ${vars}, ${path}, ${template.aspectRatio}, ${template.category})
      ON CONFLICT (id) DO NOTHING
    `;
  } catch (err) {
    logError("[image-gen] DB insert failed (image saved to disk):", err);
  }

  return { assetId, path };
}
