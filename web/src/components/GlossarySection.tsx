import { useCallback, useEffect, useState } from "react";
import { forgetTerm, listGlossary, rememberTerm } from "../api/glossary";
import { errorMessage } from "../api/http";
import type { GlossaryKind, GlossaryTerm } from "../api/types";
import { useToast } from "./Toaster";

const KINDS: ReadonlyArray<readonly [GlossaryKind, string]> = [
  ["person", "Person"],
  ["company", "Company"],
  ["product", "Product"],
  ["term", "Term"],
];

/**
 * The workspace's own vocabulary, under Workspace settings.
 *
 * The list is the safety mechanism. Terms get here from corrections — you
 * fix a name once and the workspace offers to remember it — and a
 * vocabulary that learns without showing you what it learned is one you
 * cannot trust. So: everything visible, everything removable by whoever
 * added it, nothing learned silently.
 */
export function GlossarySection() {
  const toast = useToast();
  const [terms, setTerms] = useState<GlossaryTerm[] | null>(null);
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState<GlossaryKind>("person");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTerms(await listGlossary());
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const value = term.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      await rememberTerm({ term: value, kind });
      setTerm("");
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (entry: GlossaryTerm) => {
    setBusy(true);
    try {
      await forgetTerm(entry.id);
      setTerms((cur) => cur?.filter((t) => t.id !== entry.id) ?? null);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="settings-section" aria-label="Workspace vocabulary">
      <h2>Names and terms</h2>
      <p className="help">
        Spellings this workspace uses — people, companies, products. They are given to the
        transcriber before each recording, so it hears them right instead of guessing. Fixing a
        name in a note offers to add it here.
      </p>

      <form className="glossary-add" onSubmit={(e) => void add(e)}>
        <input
          className="input"
          placeholder="John Mayer"
          aria-label="Term"
          maxLength={80}
          value={term}
          disabled={busy}
          onChange={(e) => setTerm(e.target.value)}
        />
        <div className="seg" role="group" aria-label="Kind of term">
          {KINDS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className="seg-opt"
              aria-pressed={kind === value}
              disabled={busy}
              onClick={() => setKind(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button className="btn primary" type="submit" disabled={busy || !term.trim()}>
          Add
        </button>
      </form>

      {error && <p className="help danger-text">{error}</p>}
      {terms !== null && terms.length === 0 && (
        <p className="help">
          Nothing yet. The first time you correct a name in a note, we&apos;ll offer to remember
          it.
        </p>
      )}
      {terms !== null && terms.length > 0 && (
        <ul className="glossary-list">
          {terms.map((entry) => (
            <li key={entry.id}>
              <span className="glossary-term">{entry.term}</span>
              <span className="glossary-kind">{entry.kind}</span>
              {entry.heard_as.length > 0 && (
                <span className="help glossary-heard">heard as {entry.heard_as.join(", ")}</span>
              )}
              <span className="grow" />
              {entry.can_delete && (
                <button
                  className="btn ghost sm"
                  disabled={busy}
                  onClick={() => void remove(entry)}
                  aria-label={`Forget ${entry.term}`}
                >
                  Forget
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
