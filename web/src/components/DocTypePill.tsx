import type { NoteTemplate } from "../api/types";
import { NOTE_TEMPLATE_LABELS } from "../api/types";
import { recordingTypeLabel } from "../lib/generation";
import { SparkleIcon } from "./icons";

/**
 * Meta-row pill: the template the writer used (P2), else what the engine found the recording
 * to be, else the catalogue template's name.
 */
export function DocTypePill({
  templateName,
  recordingType,
  template,
}: {
  templateName: string | null;
  recordingType?: string | null;
  template?: NoteTemplate | null;
}) {
  if (template && template !== "auto") {
    return (
      <span className="doc-pill tpl" title="The template this note was written with">
        <SparkleIcon size={13} />
        {NOTE_TEMPLATE_LABELS[template] ?? template}
      </span>
    );
  }
  const detected = recordingTypeLabel(recordingType);
  if (detected) {
    return (
      <span
        className="doc-pill tpl"
        title="Detected from the recording; change the meeting type to override"
      >
        <SparkleIcon size={13} />
        {detected}
      </span>
    );
  }
  if (!templateName) return null;
  return (
    <span className="doc-pill tpl" title="The template this note was written from">
      <SparkleIcon size={13} />
      {templateName}
    </span>
  );
}
