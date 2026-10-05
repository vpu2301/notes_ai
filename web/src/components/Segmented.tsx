import type { KeyboardEvent } from "react";

interface SegmentedProps<T extends string> {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

/**
 * A small segmented switch: equal-width options on a pill, with a thumb
 * that slides under the chosen one. A radio group to assistive tech;
 * arrow keys move the choice, as they do in a native one.
 */
export function Segmented<T extends string>({ label, options, value, onChange }: SegmentedProps<T>) {
  const index = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? 1
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? -1
          : 0;
    if (!step) return;
    e.preventDefault();
    const nextIndex = (index + step + options.length) % options.length;
    const next = options[nextIndex];
    if (!next) return;
    onChange(next.value);
    e.currentTarget.querySelectorAll("button")[nextIndex]?.focus();
  };

  return (
    <div className="segmented" role="radiogroup" aria-label={label} onKeyDown={onKey}>
      <span
        className="segmented-thumb"
        aria-hidden="true"
        style={{
          width: `calc((100% - 4px) / ${options.length})`,
          transform: `translateX(${index * 100}%)`,
        }}
      />
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
