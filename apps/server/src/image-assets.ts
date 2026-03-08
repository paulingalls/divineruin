function getImageDir(): string {
  return Bun.env.ASSET_IMAGE_DIR ?? `${import.meta.dir}/../../assets/images`;
}

export async function handleImageAsset(assetId: string): Promise<Response> {
  const safeName = assetId.replace(/[^a-zA-Z0-9_]/g, "");
  if (safeName !== assetId) {
    return Response.json({ error: "Invalid asset ID" }, { status: 400 });
  }

  const file = Bun.file(`${getImageDir()}/${safeName}.png`);
  if (!(await file.exists())) {
    return Response.json({ error: "Not found" }, { status: 404 });
  }

  return new Response(file, {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "public, max-age=86400",
      ETag: safeName,
    },
  });
}
