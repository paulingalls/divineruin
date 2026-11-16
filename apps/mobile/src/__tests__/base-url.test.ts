import { afterEach, expect, test } from "bun:test";
import { getApiBase } from "../utils/base-url";

const runtime = globalThis as typeof globalThis & { __DEV__: boolean };
const originalUrl = process.env.EXPO_PUBLIC_API_URL;
const originalDev = runtime.__DEV__;
afterEach(() => {
  if (originalUrl === undefined) delete process.env.EXPO_PUBLIC_API_URL;
  else process.env.EXPO_PUBLIC_API_URL = originalUrl;
  runtime.__DEV__ = originalDev;
});

function production(url?: string) {
  runtime.__DEV__ = false;
  if (url === undefined) delete process.env.EXPO_PUBLIC_API_URL;
  else process.env.EXPO_PUBLIC_API_URL = url;
}

test("resolved public config supplies the production URL before the environment", () => {
  production();
  const constants = { expoConfig: { extra: { apiUrl: "https://build.example.com" } } };
  expect(getApiBase(constants)).toBe("https://build.example.com");
  process.env.EXPO_PUBLIC_API_URL = "https://other.example.com";
  expect(getApiBase(constants)).toBe("https://build.example.com");
});

test("production environment fallback requires a valid HTTPS URL", () => {
  production("https://api.example.com/");
  expect(getApiBase()).toBe("https://api.example.com/");
  production();
  expect(() => getApiBase()).toThrow("EXPO_PUBLIC_API_URL");
  for (const apiUrl of ["http://api.example.com", "https://"]) {
    production(apiUrl);
    expect(() => getApiBase()).toThrow("EXPO_PUBLIC_API_URL");
    expect(() => getApiBase({ expoConfig: { extra: { apiUrl } } })).toThrow("EXPO_PUBLIC_API_URL");
  }
});

test("development keeps HTTP overrides and Metro/localhost defaults", () => {
  production("http://device.example.com:3001");
  runtime.__DEV__ = true;
  expect(getApiBase()).toBe("http://device.example.com:3001");
  delete process.env.EXPO_PUBLIC_API_URL;
  expect(getApiBase({ expoConfig: { hostUri: "192.168.1.2:8081" } })).toBe(
    "http://192.168.1.2:3001",
  );
  expect(getApiBase()).toBe("http://localhost:3001");
});
