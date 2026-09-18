import { expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { DivineFavorToast } from "@/components/hud/divine-favor-toast";

test("divine favor loss renders its negative sign", () => {
  const html = renderToStaticMarkup(<DivineFavorToast payload={{ amount: -5 }} />);

  expect(html).toContain(">-5 DIVINE FAVOR<");
});

test("divine favor gain renders its positive sign", () => {
  const html = renderToStaticMarkup(<DivineFavorToast payload={{ amount: 5 }} />);

  expect(html).toContain(">+5 DIVINE FAVOR<");
});
