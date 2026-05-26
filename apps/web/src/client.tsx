import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import { App } from "./App.tsx";

const root = document.getElementById("root");
if (!root) throw new Error("Root element #root not found");

const app = (
  <StrictMode>
    <App />
  </StrictMode>
);

// Dual-mode entry: in dev the bundler serves an empty #root (client renders),
// in production the build-time prerender (story-002) fills #root with markup
// to hydrate. childElementCount is robust against whitespace text nodes that a
// formatter might add to the prerendered HTML.
if (root.childElementCount > 0) {
  hydrateRoot(root, app);
} else {
  createRoot(root).render(app);
}
