import { describe, expect, test } from "bun:test";
import {
  AVD_NAME,
  AVD_SETTINGS,
  applyConfig,
  parseAvdNames,
  sdkTools,
  systemImage,
} from "./android-emulator.ts";

describe("systemImage", () => {
  test("uses the x86_64 Google APIs image on Intel", () => {
    expect(systemImage("x64")).toBe("system-images;android-36;google_apis;x86_64");
  });

  test("uses the arm64 Google APIs image on Apple Silicon", () => {
    expect(systemImage("arm64")).toBe("system-images;android-36;google_apis;arm64-v8a");
  });

  test("rejects other architectures", () => {
    expect(() => systemImage("ia32")).toThrow("Unsupported host architecture: ia32");
  });
});

describe("AVD_SETTINGS", () => {
  test("pins the lightweight profile", () => {
    expect(AVD_SETTINGS).toMatchObject({
      "hw.ramSize": "4096",
      "hw.cpu.ncore": "4",
      "hw.gpu.enabled": "yes",
      "hw.gpu.mode": "host",
      "PlayStore.enabled": "false",
      "hw.audioInput": "yes",
    });
  });
});

describe("applyConfig", () => {
  test("replaces existing keys in place and keeps unrelated lines", () => {
    const before = "avd.ini.encoding=UTF-8\nhw.ramSize=2048\nhw.lcd.density=420\n";
    expect(applyConfig(before, { "hw.ramSize": "4096" })).toBe(
      "avd.ini.encoding=UTF-8\nhw.ramSize=4096\nhw.lcd.density=420\n",
    );
  });

  test("appends keys the file does not have", () => {
    expect(applyConfig("hw.ramSize=4096\n", { "hw.gpu.mode": "host" })).toBe(
      "hw.ramSize=4096\nhw.gpu.mode=host\n",
    );
  });

  test("matches keys exactly, not by prefix", () => {
    const before = "hw.gpu.enabled=no\nhw.gpu.mode=auto\n";
    expect(applyConfig(before, { "hw.gpu.mode": "host" })).toBe(
      "hw.gpu.enabled=no\nhw.gpu.mode=host\n",
    );
  });

  test("tolerates spaces around the equals sign", () => {
    expect(applyConfig("hw.ramSize = 2048\n", { "hw.ramSize": "4096" })).toBe("hw.ramSize=4096\n");
  });

  test("is idempotent", () => {
    const once = applyConfig("hw.ramSize=2048\n", AVD_SETTINGS);
    expect(applyConfig(once, AVD_SETTINGS)).toBe(once);
  });
});

describe("parseAvdNames", () => {
  test("reads one name per line and ignores blanks and log noise", () => {
    const raw = "INFO    | Storing crashdata in: /tmp\nMedium_Phone\n\ndivineruin-api36\n";
    expect(parseAvdNames(raw)).toEqual(["Medium_Phone", AVD_NAME]);
  });
});

describe("sdkTools", () => {
  test("resolves every tool under ANDROID_HOME", () => {
    expect(sdkTools("/sdk")).toEqual({
      sdkmanager: "/sdk/cmdline-tools/latest/bin/sdkmanager",
      avdmanager: "/sdk/cmdline-tools/latest/bin/avdmanager",
      emulator: "/sdk/emulator/emulator",
      adb: "/sdk/platform-tools/adb",
    });
  });
});
