import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "./App.tsx";

test("App renders the hero heading", () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).toContain("Divine Ruin");
});

test("App invites visitors to the waitlist", () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).toContain("waitlist");
});

test("App mounts the NavBar and Footer chrome around the hero", () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).toContain("<nav");
  expect(html).toContain("<footer");
  // The hero <main> still sits between the chrome.
  expect(html).toMatch(/<nav[\s\S]*<main>[\s\S]*<\/main>[\s\S]*<footer/);
});
