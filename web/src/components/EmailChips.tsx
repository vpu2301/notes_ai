import { useState, type ClipboardEvent as ReactClipboardEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { AlertIcon, CheckIcon, CloseIcon } from "./icons";

/** Loose shape check — the real test is whether the server or a relay accepts it. */
export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function clean(raw: string): string {
  return raw.trim().replace(/[,;]+$/, "");
}

function unique(list: string[]): string[] {
  return list.filter((a, i) => list.findIndex((b) => b.toLowerCase() === a.toLowerCase()) === i);
}

/**
 * A chip box's state. Enter, comma, semicolon and space turn what is typed into a chip; a pasted
 * list becomes one chip per address. Anything that is not an address still becomes a chip, marked,
 * so the sender sees which one to fix; nothing is sent while one is marked.
 */
export function useEmailChips() {
  const [chips, setChips] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = (parts: string[]) => {
    const fresh = parts.map(clean).filter(Boolean);
    if (!fresh.length) return;
    setError(null);
    setChips((current) => unique([...current, ...fresh]));
  };

  /** Chip what is typed. */
  const commit = () => {
    add([draft]);
    setDraft("");
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || e.key === ";" || e.key === " ") {
      // With nothing typed, Enter submits the form.
      if (draft.trim()) {
        e.preventDefault();
        commit();
      }
      return;
    }
    const last = chips[chips.length - 1];
    if (e.key === "Backspace" && !draft && last) {
      // Backspace on an empty box edits the last chip rather than deleting it.
      setChips((current) => current.slice(0, -1));
      setDraft(last);
    }
  };

  const onPaste = (e: ReactClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData("text");
    if (!/[,;\s]/.test(text)) return;
    e.preventDefault();
    add([draft, ...text.split(/[,;\s]+/)]);
    setDraft("");
  };

  /** Everyone named, deduplicated; null (and a reason shown) when any chip is not an address. */
  const collect = (): string[] | null => {
    // A setState from `commit` has not landed yet: fold the draft in by hand.
    const all = unique([...chips, clean(draft)].filter(Boolean));
    if (draft.trim()) commit();
    const bad = all.find((a) => !EMAIL_RE.test(a));
    if (bad) {
      setError(`“${bad}” doesn’t look like an e-mail address.`);
      return null;
    }
    if (!all.length) {
      setError("Add at least one e-mail address.");
      return null;
    }
    return all;
  };

  return {
    chips,
    setChips,
    draft,
    setDraft,
    error,
    setError,
    onKeyDown,
    onPaste,
    commit,
    collect,
    composing: chips.length > 0 || draft.trim().length > 0,
    ready: chips.length > 0 || draft.trim().length > 0,
  };
}

export type EmailChipsBox = ReturnType<typeof useEmailChips>;

/** The box itself; `label` names the input for assistive tech. */
export function EmailChips({
  box,
  label,
  placeholder,
  disabled = false,
  autoFocus = false,
  className = "",
}: {
  box: EmailChipsBox;
  label: string;
  placeholder: string;
  disabled?: boolean;
  autoFocus?: boolean;
  className?: string;
}) {
  const invalid = box.chips.some((a) => !EMAIL_RE.test(a));
  return (
    <>
      <div
        className={`chip-input ${className}`}
        onClick={(e) => (e.currentTarget.querySelector("input") as HTMLInputElement | null)?.focus()}
      >
        {box.chips.map((address) => {
          const ok = EMAIL_RE.test(address);
          return (
            <span
              className={`recipient-chip ${ok ? "" : "invalid"}`}
              key={address.toLowerCase()}
              title={ok ? undefined : "Not an e-mail address"}
            >
              {address}
              <button
                type="button"
                aria-label={`Remove ${address}`}
                disabled={disabled}
                onClick={() => box.setChips((current) => current.filter((a) => a !== address))}
              >
                <CloseIcon size={11} />
              </button>
            </span>
          );
        })}
        <input
          type="email"
          multiple
          aria-label={label}
          aria-invalid={invalid || undefined}
          autoComplete="off"
          autoFocus={autoFocus}
          placeholder={box.chips.length ? "" : placeholder}
          value={box.draft}
          disabled={disabled}
          onChange={(e) => {
            box.setDraft(e.target.value);
            box.setError(null);
          }}
          onKeyDown={box.onKeyDown}
          onPaste={box.onPaste}
          onBlur={() => box.commit()}
        />
      </div>
      {box.error && (
        <span className="help danger-text" role="alert">
          {box.error}
        </span>
      )}
    </>
  );
}

/** What happened to each address after a send. */
export interface ChipResult {
  email: string;
  ok: boolean;
  text: string;
}

export function ChipResults({ results, label = "Results" }: { results: ChipResult[]; label?: string }) {
  if (!results.length) return null;
  return (
    <ul className="chip-results" aria-label={label}>
      {results.map((r) => (
        <li key={r.email.toLowerCase()} className={r.ok ? "" : "failed"}>
          {r.ok ? <CheckIcon size={13} /> : <AlertIcon size={13} />}
          <span className="chip-results-email">{r.email}</span>
          <span className="help">{r.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** "123 / 500" under a message box. */
export function CharCount({ value, max }: { value: string; max: number }) {
  return (
    <span className="help char-count" aria-live="polite">
      {value.length} / {max}
    </span>
  );
}
