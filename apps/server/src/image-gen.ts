import { GoogleGenAI, type ThinkingLevel } from "@google/genai";
import { requireEnv, logError } from "./env.ts";
import { sql } from "./db.ts";
import { resolvePrompt } from "./image-prompt-templates.ts";
import { postProcessImage } from "./image-post-process.ts";

function getImageDir(): string {
  return Bun.env.ASSET_IMAGE_DIR ?? `${import.meta.dir}/../../../assets/images`;
}

export function computeAssetId(templateId: string, vars: Record<string, string>): string {
  const sortedEntries = Object.entries(vars).sort(([a], [b]) => a.localeCompare(b));
  const payload = templateId + JSON.stringify(sortedEntries);
  const hash = new Bun.CryptoHasher("sha256").update(payload).digest("hex").slice(0, 16);
  return `img_${hash}`;
}

export function getAssetPath(assetId: string): string {
  return `${getImageDir()}/${assetId}.png`;
}

export async function assetExists(assetId: string): Promise<boolean> {
  return Bun.file(getAssetPath(assetId)).exists();
}

/**
 * Generate an image from a prompt template. Deduplicates by content-addressable ID.
 * Returns the asset ID and file path.
 */
export async function generateImage(
  templateId: string,
  vars: Record<string, string>,
  options?: { assetId?: string },
): Promise<{ assetId: string; path: string }> {
  if (options?.assetId && !/^[a-zA-Z0-9_]+$/.test(options.assetId)) {
    throw new Error(`Invalid assetId: ${options.assetId}`);
  }
  const assetId = options?.assetId ?? computeAssetId(templateId, vars);
  const path = getAssetPath(assetId);

  // Dedup: skip if already generated
  if (await Bun.file(path).exists()) {
    return { assetId, path };
  }

  const { prompt, template } = resolvePrompt(templateId, vars);

  const ai = new GoogleGenAI({ apiKey: requireEnv("GEMINI_API_KEY") });
  const response = await ai.models.generateContent({
    model: "gemini-3.1-flash-image-preview",
    contents: prompt,
    config: {
      responseModalities: ["IMAGE"],
      thinkingConfig: {
        thinkingLevel: "HIGH" as ThinkingLevel,
      },
    },
  });

  // Extract image data from response
  const parts = response.candidates?.[0]?.content?.parts;
  if (!parts) {
    throw new Error(`Gemini returned no content for template "${templateId}"`);
  }

  const imagePart = parts.find((p) => p.inlineData?.data);
  if (!imagePart?.inlineData?.data) {
    throw new Error(`Gemini returned no image data for template "${templateId}"`);
  }

  const rawBuffer = Buffer.from(imagePart.inlineData.data, "base64");

  // Post-process: darken, desaturate, crop to aspect ratio
  const processed = await postProcessImage(rawBuffer, {
    aspectRatio: template.aspectRatio,
  });

  // Ensure output directory exists
  const dir = path.substring(0, path.lastIndexOf("/"));
  await Bun.write(dir + "/.keep", "");

  await Bun.write(path, processed);

  // Record in database
  try {
    await sql`
      INSERT INTO generated_assets (id, template_id, variables, file_path, aspect_ratio, category)
      VALUES (${assetId}, ${templateId}, ${JSON.stringify(vars)}::jsonb, ${path}, ${template.aspectRatio}, ${template.category})
      ON CONFLICT (id) DO NOTHING
    `;
  } catch (err) {
    logError("[image-gen] DB insert failed (image saved to disk):", err);
  }

  return { assetId, path };
}
