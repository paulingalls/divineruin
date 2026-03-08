function getImageDir(): string {
  return Bun.env.ASSET_IMAGE_DIR ?? `${import.meta.dir}/../../assets/images`;
}

export async function handleImageAsset(assetId: string): Promise<Response> {
  // Reject anything that isn't a simple alphanumeric+underscore ID (no dots, no slashes)
  if (!/^[a-zA-Z0-9_]+$/.test(assetId)) {
    return Response.json({ error: "Invalid asset ID" }, { status: 400 });
  }

  const file = Bun.file(`${getImageDir()}/${assetId}.png`);
  if (!(await file.exists())) {
    return Response.json({ error: "Not found" }, { status: 404 });
  }

  return new Response(file, {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "public, max-age=86400",
      ETag: assetId,
    },
  });
}
