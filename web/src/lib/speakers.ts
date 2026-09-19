/**
 * A stable colour and initials for a speaker, so the same person reads
 * the same across the editor, the shared page and the native apps (they
 * use the same palette and the same hash).
 */
const TINTS = ["#4f7a5e", "#b5673c", "#8a6d2f", "#4a6d8c", "#7a5a8c", "#3f7f7a"];

export function speakerTint(name: string): string {
  let h = 0;
  for (const ch of name) h = (h + (ch.codePointAt(0) ?? 0)) % TINTS.length;
  return TINTS[h] as string;
}

export function speakerInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const pick = words.length >= 2 ? [words[0], words[words.length - 1]] : words.slice(0, 1);
  const out = pick.map((w) => (w ?? "")[0]?.toUpperCase() ?? "").join("");
  return out || "•";
}
