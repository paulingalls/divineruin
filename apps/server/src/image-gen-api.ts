import { generateImage } from "./image-gen.ts";
import { logError } from "./env.ts";
import { parseJsonBody } from "./middleware.ts";

const INTERNAL_SECRET = Bun.env.INTERNAL_SECRET ?? "";

/**
 * POST /api/images/generate
 *
 * Internal endpoint called by the DM agent to generate images during gameplay.
 * Requires X-Internal-Secret header. Returns { assetId, url }.
 */
export async function handleGenerateImage(req: Request): Promise<Response> {
  const secret = req.headers.get("X-Internal-Secret");
  if (!INTERNAL_SECRET || secret !== INTERNAL_SECRET) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await parseJsonBody<{
    templateId?: string;
    vars?: Record<string, string>;
  }>(req);
  if (!body) {
    return Response.json({ error: "Invalid Content-Type" }, { status: 415 });
  }

  if (!body.templateId) {
    return Response.json({ error: "templateId is required" }, { status: 400 });
  }

  const templateId = body.templateId;
  const vars = body.vars ?? {};

  try {
    const result = await generateImage(templateId, vars);
    return Response.json({
      assetId: result.assetId,
      url: `/api/assets/images/${result.assetId}`,
    });
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("Unknown template")) {
      return Response.json({ error: err.message }, { status: 400 });
    }
    if (err instanceof Error && err.message.startsWith("Missing required variable")) {
      return Response.json({ error: err.message }, { status: 400 });
    }
    logError("[image-gen-api] generation failed:", err);
    return Response.json({ error: "Image generation failed" }, { status: 500 });
  }
}
