import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { forgetTerm, glossaryHint, listGlossary, rememberTerm } from "../api/glossary";
import { ApiError, errorMessage } from "../api/http";
import type { GlossaryHint, GlossaryKind, GlossaryTerm } from "../api/types";
import { isVocabulary } from "../lib/glossaryRule";
import { relativeTime } from "../lib/time";
import { useToast } from "./Toaster";

const KINDS: ReadonlyArray<readonly [GlossaryKind, string]> = [
  ["person", "Person"],
  ["company", "Company"],
  ["product", "Product"],
  ["term", "Term"],
];

/** Sprint I2: the one sentence for a term that is a label, not a name —
 *  the same whether the client or the server caught it. */
export const NOT_VOCABULARY =
  "A role label like 'Moderator II' isn't a name — the transcriber won't be told it.";

function isNotVocabularyError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 422 && err.code === "term_not_vocabulary";
}

/** Sent to the transcriber unless the server says otherwise (older servers say nothing). */
function inHint(entry: GlossaryTerm): boolean {
  return entry.in_hint !== false;
}

/**
 * The workspace's own vocabulary, under Workspace settings.
 *
 * The list is the safety mechanism. Terms get here from corrections — you
 * fix a name once and the workspace offers to remember it — and a
 * vocabulary that learns without showing you what it learned is one you
 * cannot trust. So: everything visible, everything removable by whoever
 * added it, nothing learned silently.
 *
 * Sprint I2: the list is also the transcriber's prompt, word for word, so
 * the prompt is shown here as it will be sent. A speaker's role label
 * ("Moderator II") is refused before it gets in, and one that got in
 * before the rule is marked as no longer sent.
 */
export function GlossarySection() {
  const toast = useToast();
  const [terms, setTerms] = useState<GlossaryTerm[] | null>(null);
  const [hint, setHint] = useState<GlossaryHint | null>(null);
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState<GlossaryKind>("person");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, h] = await Promise.all([listGlossary(), glossaryHint()]);
      setTerms(list);
      setHint(h);
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
    if (!isVocabulary(value, kind)) {
      setAddError(NOT_VOCABULARY);
      return;
    }
    setBusy(true);
    setAddError(null);
    try {
      await rememberTerm({ term: value, kind });
      setTerm("");
      await load();
    } catch (err) {
      if (isNotVocabularyError(err)) setAddError(NOT_VOCABULARY);
      else toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (entry: GlossaryTerm) => {
    setBusy(true);
    try {
      await forgetTerm(entry.id);
      setTerms((cur) => cur?.filter((t) => t.id !== entry.id) ?? null);
      // The prompt changed; show the one the next recording will get.
      try {
        setHint(await glossaryHint());
      } catch {
        /* the list already reflects the removal; the hint refreshes on the next load */
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const notSent = terms?.filter((t) => !inHint(t)) ?? [];

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
          aria-invalid={addError ? true : undefined}
          onChange={(e) => {
            setTerm(e.target.value);
            if (addError) setAddError(null);
          }}
        />
        <div className="seg" role="group" aria-label="Kind of term">
          {KINDS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className="seg-opt"
              aria-pressed={kind === value}
              disabled={busy}
              onClick={() => {
                setKind(value);
                if (addError) setAddError(null);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <button className="btn primary" type="submit" disabled={busy || !term.trim()}>
          Add
        </button>
      </form>
      {addError && (
        <p className="help danger-text glossary-add-error" role="alert">
          {addError}
        </p>
      )}

      {error && <p className="help danger-text">{error}</p>}

      {notSent.length > 0 && (
        <div className="banner banner-warn glossary-not-sent" role="status">
          <span className="grow">
            {notSent.length === 1
              ? "1 entry is a role label, not a name — it is no longer sent to the transcriber; remove it"
              : `${notSent.length} entries are role labels, not names — they are no longer sent to the transcriber; remove them`}
          </span>
        </div>
      )}

      {terms !== null && terms.length === 0 && (
        <p className="help">
          Nothing yet. The first time you correct a name in a note, we&apos;ll offer to remember
          it.
        </p>
      )}
      {terms !== null && terms.length > 0 && (
        <ul className="glossary-list">
          {terms.map((entry) => {
            const sent = inHint(entry);
            return (
              <li key={entry.id} className={sent ? undefined : "not-sent"}>
                <span className="glossary-term">{entry.term}</span>
                <span className="glossary-kind">{entry.kind}</span>
                {!sent && <span className="glossary-tag">not sent</span>}
                {entry.heard_as.length > 0 && (
                  <span className="help glossary-heard">heard as {entry.heard_as.join(", ")}</span>
                )}
                <span className="help glossary-meta">
                  <span title={entry.created_at}>added {relativeTime(entry.created_at)}</span>
                  {entry.source_note_id && (
                    <>
                      {" · "}
                      <Link to={`/notes/${entry.source_note_id}`}>from a note</Link>
                    </>
                  )}
                </span>
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
            );
          })}
        </ul>
      )}

      {hint !== null && (
        <div className="glossary-hint" aria-label="What the transcriber is told">
          <div className="glossary-hint-h">
            <span>What the transcriber is told for the next recording</span>
            <span className="count">{hint.terms === 1 ? "1 term" : `${hint.terms} terms`}</span>
          </div>
          {hint.hint ? (
            <pre className="glossary-hint-text">{hint.hint}</pre>
          ) : (
            <p className="help">Nothing — the transcriber gets no names and guesses.</p>
          )}
        </div>
      )}
    </section>
  );
}
