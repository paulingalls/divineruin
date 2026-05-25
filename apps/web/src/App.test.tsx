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
