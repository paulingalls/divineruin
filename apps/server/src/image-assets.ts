import { findAssetPath } from "./image-dir.ts";

export async function handleImageAsset(assetId: string): Promise<Response> {
  if (!/^[a-zA-Z0-9_]+$/.test(assetId)) {
    return Response.json({ error: "Invalid asset ID" }, { status: 400 });
  }

  const path = await findAssetPath(assetId);
  if (!path) {
    return Response.json({ error: "Not found" }, { status: 404 });
  }

  return new Response(Bun.file(path), {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "public, max-age=86400",
      ETag: assetId,
    },
  });
}
