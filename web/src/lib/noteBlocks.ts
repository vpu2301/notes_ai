import type { NoteContent, NoteSection, TemplateSection } from "../api/types";
import { isTranscript } from "./richText";

/** The author's own pad: always present, never a heading. */
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
 * The sections the content HAS, in its order (structure follows content).
 * Empty blocks show only while editable and only where a picker/pad is the
 * sole way to fill them; a dialogue-shaped section is the transcript tab.
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
