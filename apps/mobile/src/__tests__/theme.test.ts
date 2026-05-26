import { test, expect } from "bun:test";
import { FontFamilies, FontStyles, TypeScale, fontStyleFor } from "@/constants/theme";
import { FontTokens } from "@divineruin/design-tokens";

// Guards the React-Native-coupled reconstruction in constants/theme.ts (the part the
// shared @divineruin/design-tokens package can't cover): that FontFamilies/FontStyles/
// TypeScale compose to the same values they did before tokens were extracted. The test
// runs under the react-native mock (test-preload.ts) where Platform.OS === "ios", so
// Platform.select resolves to the native font name and the web-only weight/italic is omitted.

test("FontFamilies resolves to the native font name on a native platform", () => {
  expect(FontFamilies.display).toBe("CormorantGaramond_300Light");
  expect(FontFamilies.body).toBe("CrimsonPro_400Regular");
  expect(FontFamilies.system).toBe("IBMPlexMono_400Regular");
});

test("FontStyles carry only the fontFamily on native (no web weight/italic)", () => {
  expect(FontStyles.display).toEqual({ fontFamily: "CormorantGaramond_300Light" });
  expect(FontStyles.displayItalic).toEqual({ fontFamily: "CormorantGaramond_300Light_Italic" });
});

// The native-only branch above is exercised under the ios preload; these call
// fontStyleFor with an explicit "web" to cover the web branch (weight + italic
// applied as CSS), which test-preload.ts (Platform.OS="ios") never reaches.
test("fontStyleFor on web carries the token weight and no fontStyle for a non-italic role", () => {
  const style = fontStyleFor("display", "web");
  expect(style.fontWeight).toBe(FontTokens.display.weight);
  expect("fontStyle" in style).toBe(false);
});

test("fontStyleFor on web adds fontStyle italic for an italic role", () => {
  const style = fontStyleFor("displayItalic", "web");
  expect(style.fontWeight).toBe(FontTokens.displayItalic.weight);
  expect(style.fontStyle).toBe("italic");
});

test("TypeScale composes size, fontFamily, lineHeight and color in order", () => {
  expect(TypeScale.display).toEqual({
    fontSize: 62,
    fontFamily: "CormorantGaramond_300Light",
    lineHeight: 68,
    color: "#D4D0C8",
  });
  expect(TypeScale.h2).toEqual({
    fontSize: 29,
    fontFamily: "CormorantGaramond_400Regular",
    lineHeight: 39,
    color: "#D4D0C8",
  });
});
