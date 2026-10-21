import { useState } from "react";
import { regenerate } from "../api/generation";
import { ApiError } from "../api/http";
import type { NoteTemplate } from "../api/types";
import { NOTE_TEMPLATES, NOTE_TEMPLATE_LABELS } from "../api/types";
import { messageFor } from "../lib/errorCopy";
import { ConfirmDialog } from "./ConfirmDialog";
import { useToast } from "./Toaster";

/**
 * "Regenerate as…" (P2): choose the template, then write the note again with it. The
 * choice sticks to the note. Any editor of a note with a recording.
 */
export function RegenerateSheet({
  noteId,
  current,
  onClose,
  onRegenerated,
}: {
  noteId: string;
  /** The template the note is set to (null: automatic). */
  current: NoteTemplate | null;
  onClose: () => void;
  /** The note is being written again: the status line should follow the new run. */
  onRegenerated: () => void;
}) {
  const toast = useToast();
  const [template, setTemplate] = useState<NoteTemplate>(current ?? "auto");
  const [busy, setBusy] = useState(false);

  const go = async () => {
    setBusy(true);
    try {
      await regenerate(noteId, template);
      toast.success(
        template === "auto"
          ? "The note is being written again; the writer chooses the template."
          : `The note is being written again as ${NOTE_TEMPLATE_LABELS[template].toLowerCase()}.`,
      );
      onRegenerated();
      onClose();
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.status === 409
          ? "This note is already being written."
          : messageFor(err),
      );
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title="Regenerate this note"
      subtitle="The note is written again from its recording. Your own typing is untouched."
      confirmLabel="Regenerate"
      busy={busy}
      onConfirm={() => void go()}
      onCancel={onClose}
    >
      <div className="seg seg-wrap" role="radiogroup" aria-label="Template">
        {NOTE_TEMPLATES.map((name) => (
          <button
            key={name}
            type="button"
            role="radio"
            className="seg-opt"
            aria-checked={template === name}
            aria-pressed={template === name}
            disabled={busy}
            onClick={() => setTemplate(name)}
          >
            {NOTE_TEMPLATE_LABELS[name]}
          </button>
        ))}
      </div>
    </ConfirmDialog>
  );
}
