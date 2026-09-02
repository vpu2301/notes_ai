import { Fragment, useMemo } from "react";

/**
 * Renders a search snippet whose only trusted markup is the
 * `<mark>…</mark>` pairs emitted by ts_headline (StartSel/StopSel).
 * Everything else is rendered as plain text (any stray tags stripped),
 * so nothing from note content can inject HTML.
 */
export function Snippet({ text }: { text: string }) {
  const parts = useMemo(() => text.split(/<mark>(.*?)<\/mark>/g), [text]);
  return (
    <span>
      {parts.map((part, i) => {
        const clean = part.replace(/<[^>]*>/g, "");
        if (!clean) return null;
        return i % 2 === 1 ? (
          <mark key={i}>{clean}</mark>
        ) : (
          <Fragment key={i}>{clean}</Fragment>
        );
      })}
    </span>
  );
}
