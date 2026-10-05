import { useEffect, useRef, useState } from "react";
import { CloseIcon, SearchIcon } from "./icons";

interface SearchFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Tooltip and aria label for the collapsed magnifier. */
  label?: string;
  /** Right-hand status while a query is live — "12 results". */
  status?: string;
  /** A search is in flight; the tail carries a quiet spinner. */
  busy?: boolean;
  className?: string;
}

/** Expandable search field: a magnifier until clicked, `/` or ⌘K; folds back when the query is cleared. */
export function SearchField({
  value,
  onChange,
  placeholder = "Search…",
  label = "Search",
  status,
  busy,
  className = "",
}: SearchFieldProps) {
  const [open, setOpen] = useState(value !== "");
  const inputRef = useRef<HTMLInputElement>(null);
  const expanded = open || value !== "";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.matches("input, textarea, select, [contenteditable]")) return;
      const slash = e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey;
      const cmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      if (!slash && !cmdK) return;
      e.preventDefault();
      setOpen(true);
      inputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <label
      className={`sf ${expanded ? "on" : ""} ${className}`.trim()}
      title={expanded ? undefined : `${label} (/)`}
      onClick={() => {
        setOpen(true);
        inputRef.current?.focus();
      }}
    >
      <span className="sf-ico" aria-hidden="true">
        <SearchIcon size={17} />
      </span>
      <input
        ref={inputRef}
        className="sf-input"
        type="search"
        value={value}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          if (value === "") setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key !== "Escape") return;
          e.preventDefault();
          // Esc clears first, folds only when empty.
          if (value !== "") onChange("");
          else {
            setOpen(false);
            inputRef.current?.blur();
          }
        }}
      />
      <span className="sf-tail">
        {busy && <span className="sf-spin" aria-hidden="true" />}
        {!busy && status && <span className="sf-status">{status}</span>}
        {value ? (
          <button
            type="button"
            className="sf-clear"
            title="Clear (esc)"
            aria-label="Clear search"
            // mousedown would blur the field first.
            onMouseDown={(e) => e.preventDefault()}
            onClick={(e) => {
              e.stopPropagation();
              onChange("");
              inputRef.current?.focus();
            }}
          >
            <CloseIcon size={13} />
          </button>
        ) : (
          <kbd className="sf-kbd">esc</kbd>
        )}
      </span>
    </label>
  );
}
