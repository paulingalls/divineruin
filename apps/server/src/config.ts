if (Bun.env.NODE_ENV === "production") {
  const required = {
    DATABASE_URL: Bun.env.DATABASE_URL,
    REDIS_URL: Bun.env.REDIS_URL,
    JWT_SECRET: Bun.env.JWT_SECRET,
    INTERNAL_SECRET: Bun.env.INTERNAL_SECRET,
    CORS_ORIGIN: Bun.env.CORS_ORIGIN,
    LIVEKIT_URL: Bun.env.LIVEKIT_URL,
    LIVEKIT_API_KEY: Bun.env.LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET: Bun.env.LIVEKIT_API_SECRET,
    GEMINI_API_KEY: Bun.env.GEMINI_API_KEY,
    RESEND_API_KEY: Bun.env.RESEND_API_KEY,
    MEDIA_DIR: Bun.env.MEDIA_DIR,
  };
  const missing = Object.entries(required)
    .filter(([, value]) => !value?.trim())
    .map(([name]) => name);
  const reasons = missing.length ? [`Missing required variables: ${missing.join(", ")}`] : [];
  if (Bun.env.EMAIL_TRANSPORT === "mock") {
    reasons.push("EMAIL_TRANSPORT=mock is refused in production");
  }
  if (reasons.length) throw new Error(`Production configuration refused: ${reasons.join("; ")}`);
}
