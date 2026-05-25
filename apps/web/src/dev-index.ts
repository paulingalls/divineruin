// Dev-only: build index.dev.html from the canonical index.html by adding the
// fonts.css <link> Bun inlines on the fly (canonical index.html omits it so the
// prod build keeps the woff2 as separate served files — see server.ts/prerender.ts).
//
// Guarded like prerender.ts's prod injection: a canonical index.html without a
// </head> would otherwise silently drop the fonts in dev (String.replace no-op).

const DEV_FONTS_LINK = '  <link rel="stylesheet" href="./src/fonts/fonts.css" />\n  </head>';

export function injectDevFontLink(canonicalHtml: string): string {
  if (!canonicalHtml.includes("</head>")) {
    throw new Error("dev index: </head> not found in index.html — cannot inject fonts.css");
  }
  return canonicalHtml.replace("</head>", DEV_FONTS_LINK);
}
