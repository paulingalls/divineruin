import sharp from "sharp";
import type { AspectRatio } from "./image-prompt-templates.ts";

const ASPECT_DIMENSIONS: Record<AspectRatio, { width: number; height: number }> = {
  "3:4": { width: 768, height: 1024 },
  "16:9": { width: 1024, height: 576 },
  "1:1": { width: 1024, height: 1024 },
  "2:3": { width: 683, height: 1024 },
  "9:16": { width: 576, height: 1024 },
};

export interface PostProcessOptions {
  aspectRatio: AspectRatio;
  targetWidth?: number;
  darken?: boolean;
  desaturate?: boolean;
}

/**
 * Post-process a generated image: darken, desaturate, crop to aspect ratio.
 * Takes a buffer, returns a buffer. No API calls.
 */
export async function postProcessImage(
  buffer: Buffer,
  options: PostProcessOptions,
): Promise<Buffer> {
  const dims = ASPECT_DIMENSIONS[options.aspectRatio];
  const scale = options.targetWidth ? options.targetWidth / dims.width : 1;
  const width = Math.round(dims.width * scale);
  const height = Math.round(dims.height * scale);

  let pipeline = sharp(buffer);

  // Darken + desaturate via modulate
  const brightness = options.darken !== false ? 0.6 : 1.0;
  const saturation = options.desaturate !== false ? 0.7 : 1.0;
  if (brightness !== 1.0 || saturation !== 1.0) {
    pipeline = pipeline.modulate({ brightness, saturation });
  }

  // Crop to target aspect ratio
  pipeline = pipeline.resize({ width, height, fit: "cover" });

  return pipeline.png().toBuffer();
}
