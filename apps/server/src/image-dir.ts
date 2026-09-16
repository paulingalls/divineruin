// `||` not `??`: .env.example ships ASSET_IMAGE_DIR= (empty), and `??` keeps that empty string,
// resolving every image path to filesystem root. An empty value means "unset", as in resolveAudioDir.
export function resolveImageDir(configured: string | undefined): string {
  return configured || `${import.meta.dir}/../../../assets/images`;
}
