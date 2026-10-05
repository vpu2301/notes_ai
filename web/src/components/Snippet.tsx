import { Fragment, useMemo } from "react";

/** Search snippet: only ts_headline's `<mark>` pairs are markup; everything else is plain text. */
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
