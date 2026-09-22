// The workspace glossary (Sprint 35).
//
// Names, companies, products and terms this workspace spells a particular
// way. Nothing is learned silently: a correction offers to remember one
// term, the list is visible under Workspace settings, and every entry can
// be deleted by whoever added it (or an admin).

import { api } from "./http";
import type { GlossaryKind, GlossaryTerm, GlossaryHint } from "./types";

export function listGlossary(): Promise<GlossaryTerm[]> {
  return api<GlossaryTerm[]>("note", "/v1/glossary");
}

/**
 * Remember one term. Sending a term the workspace already has merges the
 * new mishearing into it and answers 200 — saying "remember John Mayer"
 * after two different mistakes should teach the second one.
 */
export function rememberTerm(params: {
  term: string;
  kind?: GlossaryKind;
  heard_as?: string[];
}): Promise<GlossaryTerm> {
  return api<GlossaryTerm>("note", "/v1/glossary", { method: "POST", json: params });
}

export function forgetTerm(id: string): Promise<void> {
  return api<void>("note", `/v1/glossary/${id}`, { method: "DELETE" });
}

/** The terms as the capture form's `vocabulary_hint`. */
export function glossaryHint(): Promise<GlossaryHint> {
  return api<GlossaryHint>("note", "/v1/glossary/hint");
}
