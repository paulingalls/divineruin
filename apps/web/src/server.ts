import { serve } from "bun";
// HTML import: Bun's bundler scans index.html for <script>/<link> tags, bundles
// src/client.tsx + src/styles.css, and serves the result. In dev it bundles on
// the fly with HMR; production serving of the prerendered dist/ lands in
// story-002.
import index from "../index.html";

const isDev = process.env.NODE_ENV !== "production";

const server = serve({
  port: Number(process.env.PORT ?? 8083),
  // console: true streams the browser console to this terminal in dev.
  development: isDev ? { hmr: true, console: true } : false,
  routes: {
    "/": index,
  },
  fetch() {
    return new Response("Not found", { status: 404 });
  },
});

console.log(`Web running at ${server.url.href}`);
