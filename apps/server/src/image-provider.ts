import { GoogleGenAI, type ThinkingLevel } from "@google/genai";
import { requireEnv } from "./env.ts";

export async function requestImage(prompt: string, templateId: string): Promise<Buffer> {
  const ai = new GoogleGenAI({ apiKey: requireEnv("GEMINI_API_KEY") });
  const response = await ai.models.generateContent({
    model: "gemini-3.1-flash-image-preview",
    contents: prompt,
    config: {
      responseModalities: ["IMAGE"],
      thinkingConfig: {
        thinkingLevel: "HIGH" as ThinkingLevel,
      },
      httpOptions: {
        timeout: 120_000,
      },
    },
  });

  const parts = response.candidates?.[0]?.content?.parts;
  if (!parts) {
    throw new Error(`Gemini returned no content for template "${templateId}"`);
  }

  const imagePart = parts.find((p) => p.inlineData?.data);
  if (!imagePart?.inlineData?.data) {
    throw new Error(`Gemini returned no image data for template "${templateId}"`);
  }

  return Buffer.from(imagePart.inlineData.data, "base64");
}
