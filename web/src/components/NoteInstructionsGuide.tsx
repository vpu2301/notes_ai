// "What you can ask for" — the in-product guide to note instructions (concept §10).
// One source: the workspace card and N4's per-type and per-note editors show this.

import { PRESETS, type InstructionsPreset } from "./noteInstructionsPresets";

interface Props {
  /** Absent: no "Start from an example" choices (a member cannot edit). */
  onPreset?: (preset: InstructionsPreset) => void;
  /** The text is not empty: an example would overwrite it. */
  presetsDisabled?: boolean;
}

export function NoteInstructionsGuide({ onPreset, presetsDisabled = false }: Props) {
  return (
    <details className="instructions-guide">
      <summary>What you can ask for</summary>
      <p className="help">
        <strong>What you can ask for.</strong> How long the notes are · which optional sections to
        leave out · what to put first · which words to use and which to avoid · the style (business,
        formal, informal or academic — also a picker) · who the reader is. Write it as plain text; the headings Reader, Length,
        Sections, Emphasis, Wording and Examples help.
      </p>
      <p className="help">
        <strong>What the writer will not do.</strong> Add anything that was not said · write in the
        first person · change the language of the meeting · drop the evidence behind a line · list
        attendees · send or share notes. If you ask for one of these, you will see it under "Not
        applied".
      </p>
      <p className="help">
        <strong>Check before you save.</strong> Press <strong>Check</strong> to read what was
        understood. What you see is exactly what the writer will do on the next note.
      </p>
      {onPreset && (
        <div className="seg" role="group" aria-label="Start from an example">
          {PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className="seg-opt"
              disabled={presetsDisabled}
              title={presetsDisabled ? "Clear the text first" : undefined}
              onClick={() => onPreset(preset)}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}
    </details>
  );
}
