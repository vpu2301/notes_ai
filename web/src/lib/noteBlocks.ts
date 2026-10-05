import type { NoteContent, NoteSection, TemplateSection } from "../api/types";
import { isTranscript } from "./richText";

/** The author's own pad — the one section that is always there to type
 *  into, and never gets a heading: it is the note. */
export const PAD_KEY = "user_notes";

export interface NoteBlock {
  key: string;
  /** null = no heading. */
  title: string | null;
  /** The template's definition, when the template names this section. */
  def: TemplateSection | null;
  section: NoteSection;
}

export function isFreeText(def: TemplateSection): boolean {
  return !def.field_type || def.field_type === "free_text";
}

/**
 * What the Notes tab draws: the sections the content HAS, in its order —
 * never one per template section. Structure follows content.
 *
 * A block is shown when it has text. While the note is editable, three
 * kinds of empty block are shown too, because there is no other way to
 * put something in them: the author's pad; a typed field (choice, date,
 * number — its picker is the only way to set it); and, on a template
 * without a pad (the older, form-shaped ones), the template's own free
 * text fields. A dialogue-shaped section is the transcript and lives
 * behind its own tab.
 *
 * Headings: a template section is named by the template, an engine-made
 * section by its own `title`, and the pad and the engine's opening block
 * by nothing at all.
 */
export function noteBlocks(
  content: NoteContent | null,
  defs: TemplateSection[],
  opts: { editable: boolean },
): NoteBlock[] {
  const byId = new Map(defs.map((d) => [d.id, d] as const));
  const hasPad = byId.has(PAD_KEY);
  const out: NoteBlock[] = [];
  const seen = new Set<string>();
  const push = (key: string, section: NoteSection, def: TemplateSection | null) => {
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ key, title: titleOf(key, section, def), def, section });
  };

  for (const section of content?.sections ?? []) {
    const text = (section.text ?? "").trim();
    if (text && isTranscript(text)) continue;
    const def = byId.get(section.section_key) ?? null;
    const shownEmpty =
      opts.editable &&
      (section.section_key === PAD_KEY ||
        (def !== null && !isFreeText(def)) ||
        (!hasPad && def !== null));
    if (text || shownEmpty) push(section.section_key, section, def);
  }
  if (opts.editable) {
    for (const def of defs) {
      if (seen.has(def.id)) continue;
      if (def.id === PAD_KEY || !isFreeText(def) || !hasPad) {
        push(def.id, { section_key: def.id }, def);
      }
    }
  }
  return out;
}

function titleOf(key: string, section: NoteSection, def: TemplateSection | null): string | null {
  if (key === PAD_KEY) return null;
  if (def) return def.name;
  return section.title?.trim() || null;
}

/** A definition for a block the template does not describe: free text. */
export function defFor(block: NoteBlock): TemplateSection {
  return block.def ?? { id: block.key, name: block.title ?? "", field_type: "free_text" };
}
