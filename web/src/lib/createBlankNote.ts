import { createNote, getTemplate, listTemplates } from "../api/notes";
import type { NoteContent, TemplateSummary } from "../api/types";

/** The template a bare "new note" starts from: meeting notes, English first. */
export function defaultTemplate(list: TemplateSummary[], language = "en"): TemplateSummary | undefined {
  const live = list.filter((t) => t.status !== "archived");
  return (
    live.find((t) => t.code.startsWith("meeting_notes") && t.language === language) ??
    live.find((t) => t.code.startsWith("meeting_notes")) ??
    live[0]
  );
}

/** Create a note from a template (default: meeting notes) and return its id. */
export async function createBlankNote(templateId?: string): Promise<string> {
  let id = templateId;
  if (!id) {
    const tpl = defaultTemplate(await listTemplates());
    if (!tpl) throw new Error("Your workspace has no note templates yet.");
    id = tpl.id;
  }
  const detail = await getTemplate(id);
  const sections = [...(detail.schema_jsonb.sections ?? [])]
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map((s) => ({ section_key: s.id, text: s.default_content ?? "", field_specific_metadata: {} }));
  const content: NoteContent = {
    template_id: detail.id,
    template_schema_version: detail.schema_version,
    title: "",
    sections,
  };
  const created = await createNote(content);
  return created.id;
}
