import { useEffect, useMemo, useState } from "react";
import { correctName } from "../api/generation";
import { forgetTerm, listGlossary, rememberTerm } from "../api/glossary";
import { messageFor } from "../lib/errorCopy";
import type { GeneratedItem, GlossaryTerm } from "../api/types";

export interface NameCorrection {
  itemKey: string;
  surface: string;
  canonical: string;
  source: string;
  /** "person" only with evidence of a person; anything else is saved as a term. */
  entity?: "person" | "term";
}

const MARKED = /([A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+(?:\s[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+)?) \(\?\)/gu;

/** Names the engine respelled (once each) and the ones it doubted ("Emil (?)"). */
export function correctionsOf(rows: GeneratedItem[]): { fixed: NameCorrection[]; doubted: string[] } {
  const fixed = new Map<string, NameCorrection>();
  const doubted = new Set<string>();
  for (const row of rows) {
    for (const c of row.corrections ?? []) {
      const id = `${c.surface}→${c.canonical}`;
      if (!fixed.has(id)) fixed.set(id, { itemKey: row.item_key, ...c });
    }
    for (const m of row.text.matchAll(MARKED)) if (m[1]) doubted.add(m[1]);
  }
  return { fixed: [...fixed.values()], doubted: [...doubted] };
}

/** The saved entry that already holds this respelling, if any. */
function savedFor(c: NameCorrection, terms: GlossaryTerm[]): GlossaryTerm | undefined {
  const heard = c.surface.toLocaleLowerCase();
  return terms.find(
    (t) => t.term === c.canonical && t.heard_as.some((h) => h.toLocaleLowerCase() === heard),
  );
}

type RowState =
  | { kind: "saved"; term: GlossaryTerm }
  | { kind: "kept"; term: GlossaryTerm }
  | { kind: "rejected" }
  | { kind: "failed"; message: string };

/** Accept = a glossary term with the heard spelling as a mishearing; reject = line reverts.
 *  "In the glossary" is shown only from the server: its answer to the save, or an entry it
 *  already holds. Nothing is learned without a person saying so. */
export function CorrectionsPanel({
  noteId,
  rows,
  version,
  onChanged,
}: {
  noteId: string;
  rows: GeneratedItem[];
  version: number;
  onChanged: () => void;
}) {
  const { fixed, doubted } = useMemo(() => correctionsOf(rows), [rows]);
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [state, setState] = useState<Record<string, RowState>>({});
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (fixed.length === 0) return;
    // What is persisted decides; a failed read just shows nothing as saved.
    listGlossary()
      .then((saved) => setTerms(Array.isArray(saved) ? saved : []))
      .catch(() => setTerms([]));
  }, [fixed.length]);

  if (fixed.length === 0 && doubted.length === 0) return null;

  const accept = async (c: NameCorrection, id: string) => {
    let saved: GlossaryTerm;
    try {
      saved = await rememberTerm({
        term: c.canonical,
        kind: c.entity === "person" ? "person" : "term",
        heard_as: [c.surface],
        note_id: noteId,
      });
    } catch (err) {
      setState((s) => ({ ...s, [id]: { kind: "failed", message: messageFor(err) } }));
      return;
    }
    setTerms((t) => [...t.filter((x) => x.id !== saved.id), saved]);
    const learned = savedFor(c, [saved]);
    setState((s) => ({ ...s, [id]: learned ? { kind: "saved", term: saved } : { kind: "kept", term: saved } }));
    try {
      await correctName(noteId, c.itemKey, {
        expected_version: version,
        action: "correction_accepted",
        surface: c.surface,
        canonical: c.canonical,
        source: c.source,
      });
    } catch {
      // The glossary entry stands; the note just asks again next time.
    }
  };

  const reject = async (c: NameCorrection, id: string) => {
    try {
      await correctName(noteId, c.itemKey, {
        expected_version: version,
        action: "correction_rejected",
        surface: c.surface,
        canonical: c.canonical,
        source: c.source,
      });
      setState((s) => ({ ...s, [id]: { kind: "rejected" } }));
      onChanged();
    } catch (err) {
      setState((s) => ({ ...s, [id]: { kind: "failed", message: messageFor(err) } }));
    }
  };

  const remove = async (term: GlossaryTerm, id: string) => {
    try {
      await forgetTerm(term.id);
      setTerms((t) => t.filter((x) => x.id !== term.id));
      setState((s) => {
        const next = { ...s };
        delete next[id];
        return next;
      });
    } catch (err) {
      setState((s) => ({ ...s, [id]: { kind: "failed", message: messageFor(err) } }));
    }
  };

  const run = async (id: string, work: () => Promise<void>) => {
    setBusy(id);
    try {
      await work();
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="corrections-panel" aria-label="Names in this note">
      <h3 className="section-name">Names in this note</h3>
      <ul>
        {fixed.map((c) => {
          const id = `${c.surface}→${c.canonical}`;
          const current = state[id];
          const persisted = current?.kind === "saved" ? current.term : savedFor(c, terms);
          return (
            <li key={id}>
              <span>
                <span className="muted">heard</span> {c.surface} → <strong>{c.canonical}</strong>
                {c.entity !== "person" && <span className="muted"> (suggested term)</span>}
              </span>
              {persisted ? (
                <>
                  <span className="muted">In the glossary</span>
                  {persisted.can_delete && (
                    <button
                      type="button"
                      className="btn ghost sm"
                      disabled={busy === id}
                      onClick={() => void run(id, () => remove(persisted, id))}
                    >
                      Remove
                    </button>
                  )}
                </>
              ) : current?.kind === "kept" ? (
                <span className="muted">
                  Saved “{current.term.term}”, but “{c.surface}” was not learned: it only differs in
                  grammar
                </span>
              ) : current?.kind === "rejected" ? (
                <span className="muted">Put back as heard</span>
              ) : (
                <>
                  {current?.kind === "failed" && (
                    <span className="danger-text" role="alert">
                      Not saved: {current.message}
                    </span>
                  )}
                  <button
                    type="button"
                    className="btn sm"
                    disabled={busy === id}
                    onClick={() => void run(id, () => accept(c, id))}
                  >
                    {current?.kind === "failed" ? "Try again" : "Accept"}
                  </button>
                  <button
                    type="button"
                    className="btn ghost sm"
                    disabled={busy === id}
                    onClick={() => void run(id, () => reject(c, id))}
                  >
                    Reject
                  </button>
                </>
              )}
            </li>
          );
        })}
        {doubted.map((name) => (
          <li key={`?${name}`}>
            <span>
              {name} <span className="muted">(?) — not sure of the spelling</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
