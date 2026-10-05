import { useMemo, useState } from "react";
import { correctName } from "../api/generation";
import { rememberTerm } from "../api/glossary";
import { messageFor } from "../lib/errorCopy";
import type { GeneratedItem } from "../api/types";

export interface NameCorrection {
  itemKey: string;
  surface: string;
  canonical: string;
  source: string;
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

/** Accept = glossary term with the heard spelling as a mishearing; reject = line reverts.
 *  Nothing is learned without a person saying so. */
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
  const [done, setDone] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  if (fixed.length === 0 && doubted.length === 0) return null;

  const act = async (c: NameCorrection, accept: boolean) => {
    const id = `${c.surface}→${c.canonical}`;
    setBusy(id);
    setProblem(null);
    try {
      if (accept) {
        await rememberTerm({ term: c.canonical, kind: "person", heard_as: [c.surface] });
      }
      await correctName(noteId, c.itemKey, {
        expected_version: version,
        action: accept ? "correction_accepted" : "correction_rejected",
        surface: c.surface,
        canonical: c.canonical,
        source: c.source,
      });
      setDone((d) => ({ ...d, [id]: accept ? "Added to the glossary" : "Put back as heard" }));
      if (!accept) onChanged();
    } catch (err) {
      setProblem(messageFor(err));
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
          return (
            <li key={id}>
              <span>
                <span className="muted">heard</span> {c.surface} → <strong>{c.canonical}</strong>
              </span>
              {done[id] ? (
                <span className="muted">{done[id]}</span>
              ) : (
                <>
                  <button type="button" className="btn sm" disabled={busy === id} onClick={() => void act(c, true)}>
                    Accept
                  </button>
                  <button type="button" className="btn ghost sm" disabled={busy === id} onClick={() => void act(c, false)}>
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
      {problem && <p className="banner banner-warn">{problem}</p>}
    </section>
  );
}
