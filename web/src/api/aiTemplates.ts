// The writer's templates (P2): the built-in text per language, or this workspace's own over it.
import { api } from "./http";
import type { NoteTemplate, TemplateLanguage, WorkspaceTemplate } from "./types";

export function getTemplates(language: TemplateLanguage): Promise<WorkspaceTemplate[]> {
  return api<WorkspaceTemplate[]>("note", "/v1/ai/templates", { query: { language } });
}

export function putTemplate(
  name: NoteTemplate,
  body: { language: TemplateLanguage; markdown: string },
): Promise<WorkspaceTemplate> {
  return api<WorkspaceTemplate>("note", `/v1/ai/templates/${name}`, { method: "PUT", json: body });
}

/** Back to the built-in text. */
export function deleteTemplate(name: NoteTemplate, language: TemplateLanguage): Promise<void> {
  return api<void>("note", `/v1/ai/templates/${name}`, { method: "DELETE", query: { language } });
}
