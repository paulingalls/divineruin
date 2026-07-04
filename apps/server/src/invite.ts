/** High-entropy, URL-safe invite code — the capability secret for redeem. */
export function generateCode(): string {
  return Buffer.from(crypto.getRandomValues(new Uint8Array(8))).toString("base64url");
}
