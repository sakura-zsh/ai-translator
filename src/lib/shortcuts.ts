/** Match Qt-style hotkey strings like "Ctrl+Return", "Ctrl+Shift+S", "Ctrl+Alt+T". */
export function matchesShortcut(event: KeyboardEvent, spec: string): boolean {
  const clean = (spec || "").trim();
  if (!clean) return false;

  const parts = clean.split("+").map((p) => p.trim().toLowerCase());
  const keyPart = parts.pop();
  if (!keyPart) return false;

  const needCtrl = parts.includes("ctrl") || parts.includes("control");
  const needShift = parts.includes("shift");
  const needAlt = parts.includes("alt");
  const needMeta = parts.includes("meta") || parts.includes("super") || parts.includes("win");

  if (event.ctrlKey !== needCtrl) return false;
  if (event.shiftKey !== needShift) return false;
  if (event.altKey !== needAlt) return false;
  if (event.metaKey !== needMeta) return false;

  const evKey = event.key.toLowerCase();
  const normalizedTarget =
    keyPart === "return" || keyPart === "enter"
      ? "enter"
      : keyPart === "esc"
        ? "escape"
        : keyPart === "space"
          ? " "
          : keyPart;

  return evKey === normalizedTarget;
}
