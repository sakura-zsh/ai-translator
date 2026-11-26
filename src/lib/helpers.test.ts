import { describe, expect, it } from "vitest";
import { matchesShortcut } from "./shortcuts";
import {
  MODEL_AUTO,
  MODEL_VISION,
  displayModelLabel,
  likelyReasoningModel,
  truncateLabel,
} from "./types";

describe("types helpers", () => {
  it("formats sentinel model labels and truncates long ids", () => {
    expect(displayModelLabel(MODEL_AUTO)).toBe("自动选择");
    expect(displayModelLabel(MODEL_VISION)).toBe("跟随视觉模型");
    expect(displayModelLabel("gpt-4o-mini")).toBe("gpt-4o-mini");
    expect(truncateLabel("a".repeat(35), 30)).toBe(`${"a".repeat(29)}…`);
  });

  it("detects reasoning model names", () => {
    expect(likelyReasoningModel("deepseek-reasoner")).toBe(true);
    expect(likelyReasoningModel("deepseek-r1")).toBe(true);
    expect(likelyReasoningModel("o3-mini")).toBe(true);
    expect(likelyReasoningModel("gpt-4o-mini")).toBe(false);
  });
});

describe("matchesShortcut", () => {
  it("matches Ctrl+Return and Ctrl+Shift+S", () => {
    const enterEv = {
      key: "Enter",
      ctrlKey: true,
      shiftKey: false,
      altKey: false,
      metaKey: false,
    } as KeyboardEvent;
    expect(matchesShortcut(enterEv, "Ctrl+Return")).toBe(true);
    expect(matchesShortcut(enterEv, "Ctrl+Shift+S")).toBe(false);

    const shotEv = {
      key: "s",
      ctrlKey: true,
      shiftKey: true,
      altKey: false,
      metaKey: false,
    } as KeyboardEvent;
    expect(matchesShortcut(shotEv, "Ctrl+Shift+S")).toBe(true);
  });
});
