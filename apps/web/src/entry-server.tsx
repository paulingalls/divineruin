import { prerender } from "react-dom/static";
import { App } from "./App.tsx";

// Build-time SSG seam. Renders the SAME App the client hydrates (client.tsx)
// to a fully-resolved static HTML string via React 19's react-dom/static
// prerender. Component identity between here and the client is what keeps the
// prerendered markup byte-compatible with hydration. `prerender` returns a
// stream (prelude); read it fully before use.
export async function renderAppHTML(): Promise<string> {
  const { prelude } = await prerender(<App />);
  return await new Response(prelude).text();
}
