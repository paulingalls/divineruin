import { resolveApiUrl } from "@/utils/base-url";

export function cachedImageUri(uri: string | null | undefined, apiBase: string): string | null {
  if (!uri) return null;
  const clean = uri.replace(/^"|"$/g, "");
  return clean ? resolveApiUrl(clean, apiBase) : null;
}
