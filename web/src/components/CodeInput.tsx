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
 * Six-box one-time-code field. One `<input>` per digit is what earns iOS/macOS
 * "From Messages" autofill and Android's SMS prompt. Autofill lands the whole
 * code in box 0, so every box spreads a multi-character value rightwards.
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
  // Guards against a double fire when the last digit completes and re-renders.
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
      // The value is a compact digit string (no holes), so Backspace truncates from the caret.
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
    // The mail groups the code ("482 913"): keep digits only.
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
          // Only box 0 gets the autofill hint: on all six, Safari offers the code six times.
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
