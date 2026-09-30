/**
 * A stable colour and initials for a speaker, so the same person reads
 * the same across the editor, the shared page and the native apps (they
 * use the same palette and the same hash).
 */
const TINT_COUNT = 6;

/** A CSS colour for `--tint`: one of the `--speaker-N` tokens (tokens.css), which carry their own dark-mode values. */
export function speakerTint(name: string): string {
  let h = 0;
  for (const ch of name) h = (h + (ch.codePointAt(0) ?? 0)) % TINT_COUNT;
  return `var(--speaker-${h + 1})`;
}

export function speakerInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const pick = words.length >= 2 ? [words[0], words[words.length - 1]] : words.slice(0, 1);
  const out = pick.map((w) => (w ?? "")[0]?.toUpperCase() ?? "").join("");
  return out || "•";
}

function nameKey(name: string): string {
  return name.trim().toLocaleLowerCase();
}

/**
 * The names a rename can offer for `label`: the job's `name_candidates`
 * (calendar invitees) minus any already given to another speaker, in the
 * server's order, without repeats.
 */
export function pickableNames(
  candidates: readonly string[] | undefined,
  names: Record<string, string>,
  label: string,
): string[] {
  const used = new Set(
    Object.entries(names)
      .filter(([l]) => l !== label)
      .map(([, n]) => nameKey(n)),
  );
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of candidates ?? []) {
    const key = nameKey(c);
    if (!key || used.has(key) || seen.has(key)) continue;
    seen.add(key);
    out.push(c.trim());
  }
  return out;
}

/**
 * The segment indices of some turns, concatenated in transcript order —
 * one reassign call per action however many turns are selected. They are
 * opaque (artifact index space): sent back exactly as the result gave them.
 */
export function segmentIndicesOf(turns: ReadonlyArray<{ segment_indices?: number[] }>): number[] {
  return turns.flatMap((t) => t.segment_indices ?? []);
}
