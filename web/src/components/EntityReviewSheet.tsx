import { useEffect, useState } from "react";
import { decideCorrection, listCorrections } from "../api/asr";
import { rememberTerm } from "../api/glossary";
import { ApiError } from "../api/http";
import type { CorrectionsView, EntityCorrection } from "../api/types";
import { needsReview } from "../lib/corrections";

/**
 * Sprint TQ3: one row per unified spelling — canonical, the variants it
 * replaced, how often, and where the spelling came from. Accept applies it
 * on every surface; Reject puts every occurrence back. Accepting a spelling
 * from the glossary teaches it the variants (`heard_as`); any other can be
 * added to the glossary from here. Offline the sheet is read-only: the
 * corrections live on the server's view.
 */
interface EntityReviewSheetProps {
  jobId: string;
  corrections: EntityCorrection[];
  rev: number;
  online: boolean;
  onChanged: (view: CorrectionsView) => void;
  /** The spelling under the pointer, so the transcript can highlight it. */
  onHover?: (text: string | null) => void;
  onClose: () => void;
}

const SOURCE: Record<EntityCorrection["source"], string> = {
  glossary: "glossary",
  calendar: "calendar",
  hint: "vocabulary hint",
  majority: "most frequent spelling",
  user: "edited",
};

export function EntityReviewSheet({
  jobId,
  corrections,
  rev,
  online,
  onChanged,
  onHover,
  onClose,
}: EntityReviewSheetProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const [learned, setLearned] = useState<ReadonlySet<string>>(() => new Set());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = corrections.filter(needsReview);

  // The last spelling decided: nothing left to review.
  useEffect(() => {
    if (rows.length === 0) onClose();
  }, [rows.length, onClose]);

  const remember = async (c: EntityCorrection, toText: string) => {
    await rememberTerm({ term: toText, kind: c.source === "calendar" ? "person" : "term", heard_as: c.from_forms });
    setLearned((s) => new Set(s).add(c.id));
  };

  const decide = async (c: EntityCorrection, status: "accepted" | "rejected", toText?: string) => {
    setBusy(c.id);
    setError(null);
    try {
      const view = await decideCorrection(jobId, c.id, {
        status,
        corrections_rev: rev,
        ...(toText && toText !== c.to_text ? { to_text: toText } : {}),
      });
      onChanged(view);
      setEditing(null);
      // A spelling the glossary gave: its variants are mishearings worth
      // remembering (the glossary merges them into the existing term).
      if (status === "accepted" && c.source === "glossary") {
        await remember(c, toText ?? c.to_text).catch(() => undefined);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("These spellings changed in the meantime — reloaded, please check again.");
        onChanged(await listCorrections(jobId));
      } else {
        setError("Couldn't save that — try again.");
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal entity-review" role="dialog" aria-modal="true" aria-label="Unified spellings">
        <div className="modal-h">
          <h2>Unified spellings</h2>
          <p>One name, one spelling across the transcript, the note and its quotes. Nothing in the recording changes.</p>
        </div>
        <div className="modal-b">
          {rows.length === 0 && <p className="help">Nothing to review.</p>}
          {rows.map((c) => {
            const isEditing = editing?.id === c.id;
            const locked = !online || busy !== null;
            return (
              <div
                key={c.id}
                className={`entity-row ${c.status}`}
                data-testid="entity-row"
                onMouseEnter={() => onHover?.(c.to_text)}
                onMouseLeave={() => onHover?.(null)}
              >
                <div className="entity-row-h">
                  {isEditing ? (
                    <input
                      className="input sm"
                      aria-label="Spelling"
                      value={editing.value}
                      maxLength={80}
                      onChange={(e) => setEditing({ id: c.id, value: e.target.value })}
                    />
                  ) : (
                    <strong>{c.to_text}</strong>
                  )}
                  <span className="help">
                    {c.status === "proposed" ? "proposed" : "applied"} · {c.occurrences_count}× · {SOURCE[c.source]}
                  </span>
                </div>
                <div className="help entity-variants">replaces: {c.from_forms.join(", ")}</div>
                <div className="entity-actions">
                  {isEditing ? (
                    <>
                      <button
                        className="btn sm primary"
                        disabled={locked || !editing.value.trim()}
                        onClick={() => void decide(c, "accepted", editing.value.trim())}
                      >
                        Save
                      </button>
                      <button className="btn sm ghost" onClick={() => setEditing(null)}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      {c.status === "proposed" && (
                        <button className="btn sm primary" disabled={locked} onClick={() => void decide(c, "accepted")}>
                          Accept
                        </button>
                      )}
                      <button className="btn sm ghost" disabled={locked} onClick={() => void decide(c, "rejected")}>
                        Reject
                      </button>
                      <button
                        className="btn sm ghost"
                        disabled={locked}
                        onClick={() => setEditing({ id: c.id, value: c.to_text })}
                      >
                        Edit
                      </button>
                      {c.status === "accepted" && c.source !== "glossary" && !learned.has(c.id) && (
                        <button
                          className="btn sm ghost"
                          disabled={locked}
                          onClick={() => void remember(c, c.to_text).catch(() => setError("Couldn't add it to the glossary."))}
                        >
                          Add to glossary
                        </button>
                      )}
                      {learned.has(c.id) && <span className="help">in the glossary</span>}
                    </>
                  )}
                </div>
              </div>
            );
          })}
          {!online && <p className="help">Offline — reviewing needs a connection.</p>}
          {error && (
            <div className="banner banner-danger" role="alert">
              <span className="grow">{error}</span>
            </div>
          )}
        </div>
        <div className="modal-f">
          <button className="btn" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
