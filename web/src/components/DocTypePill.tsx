import { recordingTypeLabel } from "../lib/generation";
import { SparkleIcon } from "./icons";

/** Meta-row pill: the template's name, unless the engine found the recording is something else. */
export function DocTypePill({
  templateName,
  recordingType,
}: {
  templateName: string | null;
  recordingType?: string | null;
}) {
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
