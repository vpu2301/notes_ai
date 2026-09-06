import { useEffect, useRef, type ClipboardEvent, type KeyboardEvent } from "react";

interface CodeInputProps {
  value: string;
  onChange: (value: string) => void;
  /** Fired once the last box is filled — by typing, pasting or autofill. */
  onComplete: (value: string) => void;
  length?: number;
  disabled?: boolean;
  /** Plays the shake once; flip it back off when the user edits. */
  invalid?: boolean;
  label?: string;
  describedBy?: string;
}

/**
 * The six-box one-time-code field.
 *
 * One real `<input>` per digit, because that is what gives iOS and macOS
 * the "From Messages" autofill and Android the SMS Retriever prompt — a
 * single masked field gets neither. The cost is that paste, backspace and
 * arrow keys all have to be re-implemented, which is what most of this
 * file is.
 *
 * Autofill lands the whole code in box 0 rather than one digit per box, so
 * every input spreads a multi-character value across its successors rather
 * than truncating it. That one rule covers paste, autofill and a fast
 * typist equally.
 */
export function CodeInput({
  value,
  onChange,
  onComplete,
  length = 6,
  disabled = false,
  invalid = false,
  label = "Verification code",
  describedBy,
}: CodeInputProps) {
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  // Guards against firing twice when the last digit both completes the code
  // and triggers a re-render.
  const completed = useRef(false);

  useEffect(() => {
    if (value.length < length) completed.current = false;
  }, [value, length]);

  const commit = (next: string) => {
    const digits = next.replace(/\D/g, "").slice(0, length);
    onChange(digits);
    if (digits.length === length && !completed.current) {
      completed.current = true;
      onComplete(digits);
    }
    return digits;
  };

  const focusBox = (i: number) => {
    const target = Math.max(0, Math.min(length - 1, i));
    boxes.current[target]?.focus();
    boxes.current[target]?.select();
  };

  const onBoxChange = (index: number, raw: string) => {
    const digits = raw.replace(/\D/g, "");
    if (!digits) return;
    // Splice this box's digits in, then let anything extra flow rightwards.
    const next = (value.slice(0, index) + digits + value.slice(index + digits.length)).slice(
      0,
      length,
    );
    const settled = commit(next);
    focusBox(Math.min(index + digits.length, length - 1));
    if (settled.length === length) boxes.current[length - 1]?.blur();
  };

  const onKeyDown = (index: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace") {
      e.preventDefault();
      // The value is a compact digit string, so there is no way to hold a
      // hole in the middle. Backspace therefore truncates from the caret —
      // which is also what people expect from a code field: it rubs out
      // what you just typed rather than leaving a gap behind.
      if (value[index]) {
        onChange(value.slice(0, index));
      } else {
        onChange(value.slice(0, Math.max(0, index - 1)));
        focusBox(index - 1);
      }
      completed.current = false;
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusBox(index - 1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      focusBox(index + 1);
    }
  };

  const onPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    // The mail shows the code grouped ("482 913"); strip anything that is
    // not a digit so a copied group still lands correctly.
    const digits = commit(e.clipboardData.getData("text"));
    focusBox(digits.length);
  };

  return (
    <div
      className={`code-input ${invalid ? "invalid" : ""}`}
      role="group"
      aria-label={label}
      aria-describedby={describedBy}
    >
      {Array.from({ length }, (_, i) => (
        <input
          key={i}
          ref={(el) => {
            boxes.current[i] = el;
          }}
          type="text"
          inputMode="numeric"
          // Only the first box claims the autofill hint: naming it on all
          // six makes Safari offer the same code six times.
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={length}
          disabled={disabled}
          autoFocus={i === 0}
          aria-label={`Digit ${i + 1} of ${length}`}
          value={value[i] ?? ""}
          onChange={(e) => onBoxChange(i, e.target.value)}
          onKeyDown={(e) => onKeyDown(i, e)}
          onPaste={onPaste}
          onFocus={(e) => e.target.select()}
        />
      ))}
    </div>
  );
}
