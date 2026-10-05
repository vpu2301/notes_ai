// The workspace glossary. Nothing is learned silently; every entry is visible and deletable.

import { api } from "./http";
import type { GlossaryKind, GlossaryTerm, GlossaryHint } from "./types";

export function listGlossary(): Promise<GlossaryTerm[]> {
  return api<GlossaryTerm[]>("note", "/v1/glossary");
}

/** An existing term merges the new mishearing in and answers 200. */
export function rememberTerm(params: {
  term: string;
  kind?: GlossaryKind;
  heard_as?: string[];
  /** The note the rename happened in. */
  note_id?: string;
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
