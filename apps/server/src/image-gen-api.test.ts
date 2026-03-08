import { test, expect, describe, mock, beforeEach, afterEach } from "bun:test";
import { join } from "path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import sharp from "sharp";

import { _setInternalSecretForTesting } from "./middleware.ts";
_setInternalSecretForTesting("test-secret");

// Create a small valid PNG for mock responses
async function makeFakeBase64Png(): Promise<string> {
  const buf = await sharp({
    create: { width: 64, height: 64, channels: 3, background: { r: 80, g: 80, b: 80 } },
  })
    .png()
    .toBuffer();
  return buf.toString("base64");
}

let tmpDir: string;
let fakeB64: string;

beforeEach(async () => {
  tmpDir = await mkdtemp(join(tmpdir(), "img-api-test-"));
  fakeB64 = await makeFakeBase64Png();
  process.env.ASSET_IMAGE_DIR = tmpDir;
  process.env.GEMINI_API_KEY = "test-key";
});

afterEach(async () => {
  await rm(tmpDir, { recursive: true, force: true });
  delete process.env.ASSET_IMAGE_DIR;
  delete process.env.GEMINI_API_KEY;
});

// Mock @google/genai
await mock.module("@google/genai", () => ({
  GoogleGenAI: class {
    models = {
      generateContent: () =>
        Promise.resolve({
          candidates: [
            {
              content: {
                parts: [{ inlineData: { data: fakeB64, mimeType: "image/png" } }],
              },
            },
          ],
        }),
    };
  },
}));

// Mock db to avoid real database connection
await mock.module("./db.ts", () => ({
  sql: Object.assign(
    (_strings: TemplateStringsArray, ..._values: unknown[]) => Promise.resolve([]),
    { begin: (fn: (tx: unknown) => Promise<unknown>) => fn({}) },
  ),
}));

const { handleGenerateImage } = await import("./image-gen-api.ts");

function makeRequest(body?: Record<string, unknown>, headers?: Record<string, string>): Request {
  const opts: RequestInit = { method: "POST" };
  if (body) {
    opts.body = JSON.stringify(body);
    opts.headers = { "Content-Type": "application/json", ...headers };
  } else if (headers) {
    opts.headers = headers;
  }
  return new Request("http://localhost/api/images/generate", opts);
}

const secretHeaders = { "X-Internal-Secret": "test-secret" };

describe("handleGenerateImage", () => {
  test("rejects request without secret", async () => {
    const req = makeRequest({ templateId: "ui_loading_abstract" });
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("Unauthorized");
  });

  test("rejects request with wrong secret", async () => {
    const req = makeRequest(
      { templateId: "ui_loading_abstract" },
      {
        "X-Internal-Secret": "wrong-secret",
      },
    );
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(401);
  });

  test("rejects missing Content-Type", async () => {
    const req = new Request("http://localhost/api/images/generate", {
      method: "POST",
      headers: { "X-Internal-Secret": "test-secret" },
      body: JSON.stringify({ templateId: "ui_loading_abstract" }),
    });
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(415);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("Invalid Content-Type");
  });

  test("rejects missing templateId", async () => {
    const req = makeRequest({ vars: {} }, secretHeaders);
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("templateId is required");
  });

  test("returns 400 for unknown template", async () => {
    const req = makeRequest({ templateId: "nonexistent_template_xyz" }, secretHeaders);
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Unknown template");
  });

  test("returns 400 for missing required variable", async () => {
    const req = makeRequest({ templateId: "npc_portrait", vars: {} }, secretHeaders);
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Missing required variable");
  });

  test("generates image and returns assetId and url", async () => {
    const req = makeRequest({ templateId: "ui_loading_abstract" }, secretHeaders);
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { assetId: string; url: string };
    expect(body.assetId).toMatch(/^img_[a-f0-9]{16}$/);
    expect(body.url).toBe(`/api/assets/images/${body.assetId}`);
  });

  test("generates image with template variables", async () => {
    const req = makeRequest(
      {
        templateId: "npc_portrait",
        vars: {
          description: "a grizzled old warrior",
          features: "deep scars and a missing eye",
        },
      },
      secretHeaders,
    );
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { assetId: string; url: string };
    expect(body.assetId).toMatch(/^img_[a-f0-9]{16}$/);
    expect(body.url).toStartWith("/api/assets/images/img_");
  });

  test("defaults vars to empty object when not provided", async () => {
    const req = makeRequest({ templateId: "ui_loading_abstract" }, secretHeaders);
    const res = await handleGenerateImage(req);
    expect(res.status).toBe(200);
  });
});
