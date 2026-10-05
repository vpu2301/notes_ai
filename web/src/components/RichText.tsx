import React, { Fragment, type ReactNode, useMemo } from "react";
import { type Block, type Inline, type ListItem, parseRichText } from "../lib/richText";
import { speakerInitials, speakerTint } from "../lib/speakers";

/** Inline runs — code, bold and italic; everything else is plain text. */
function Spans({ spans }: { spans: Inline[] }) {
  return (
    <>
      {spans.map((s, i) => {
        if (s.code) return <code key={i}>{s.text}</code>;
        if (s.bold) return <strong key={i}>{s.text}</strong>;
        if (s.italic) return <em key={i}>{s.text}</em>;
        return <Fragment key={i}>{s.text}</Fragment>;
      })}
    </>
  );
}

/** One list level plus everything nested under it; returns the index to carry on from. */
/** Drawn at the end of one line from its source text (the evidence affordance). */
export type LineExtra = (raw: string) => ReactNode;

function buildList(
  items: ListItem[],
  start: number,
  depth: number,
  extra?: LineExtra,
): { node: ReactNode; next: number } {
  const first = items[start] as ListItem;
  const ordered = first.ordered;
  const checklist = first.done !== undefined;
  /** Each entry is one <li>: its own text, plus whatever nests under it. */
  const rows: { item: ListItem; sub: ReactNode }[] = [];
  let i = start;

  for (let item = items[i]; item !== undefined && item.depth >= depth; item = items[i]) {
    if (item.depth > depth) {
      // Deeper: nests under the item just placed; with nothing above, a stray indent is ours.
      const sub = buildList(items, i, item.depth, extra);
      const parent = rows[rows.length - 1];
      if (!parent) return sub;
      parent.sub = sub.node;
      i = sub.next;
      continue;
    }
    if (item.ordered !== ordered || (item.done !== undefined) !== checklist) break;
    rows.push({ item, sub: null });
    i++;
  }

  const lis = rows.map(({ item, sub }, k) => (
    <li key={k} className={checklist ? "task" : undefined}>
      {checklist && <span className={`box${item.done ? " done" : ""}`} aria-hidden="true" />}
      <span>
        <Spans spans={item.spans} />
        {extra && item.raw ? extra(item.raw) : null}
      </span>
      {sub}
    </li>
  ));

  const cls = `rt-list d${Math.min(depth, 2)}${checklist ? " checklist" : ""}`;
  const node = ordered ? (
    <ol className={cls} start={first.num ?? 1}>
      {lis}
    </ol>
  ) : (
    <ul className={cls}>{lis}</ul>
  );
  return { node, next: i };
}

function Blocks({ blocks, extra }: { blocks: Block[]; extra?: LineExtra }) {
  const out: ReactNode[] = [];
  blocks.forEach((block, b) => {
    switch (block.kind) {
      case "heading": {
        // The gutter "#" is drawn by CSS.
        const H = (`h${block.level}` as unknown) as "h3";
        out.push(
          <H key={b} className="rt-h" data-level={block.level}>
            <Spans spans={block.spans} />
          </H>,
        );
        break;
      }
      case "para":
        if (block.speaker) {
          out.push(
            <div key={b} className="rt-turn">
              <span className="speaker-avatar" style={{ "--tint": speakerTint(block.speaker) } as React.CSSProperties} aria-hidden="true">
                {speakerInitials(block.speaker)}
              </span>
              <span className="rt-speaker">{block.speaker}</span>
              <p className="rt-p rt-turn-text">
                <Spans spans={block.spans} />
              </p>
            </div>,
          );
          break;
        }
        out.push(
          <p key={b} className="rt-p">
            <Spans spans={block.spans} />
            {extra && block.raw ? extra(block.raw) : null}
          </p>,
        );
        break;
      case "quote":
        out.push(
          <blockquote key={b} className="rt-quote">
            <Spans spans={block.spans} />
          </blockquote>,
        );
        break;
      case "rule":
        out.push(<hr key={b} className="rt-rule" />);
        break;
      case "table":
        out.push(
          <div key={b} className="rt-table-wrap">
            <table className="rt-table">
              <thead>
                <tr>
                  {block.head.map((cell, i) => (
                    <th key={i}>
                      <Spans spans={cell} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j}>
                        <Spans spans={cell} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>,
        );
        break;
      case "list": {
        let i = 0;
        while (i < block.items.length) {
          const { node, next } = buildList(block.items, i, (block.items[i] as ListItem).depth, extra);
          out.push(<Fragment key={`${b}-${i}`}>{node}</Fragment>);
          i = next > i ? next : i + 1;
        }
        break;
      }
    }
  });
  return <>{out}</>;
}

interface RichTextProps {
  text: string;
  /** Shown in place of an empty body. */
  placeholder?: string;
  className?: string;
  /** Drawn at the end of each paragraph and list item, from its source. */
  lineExtra?: LineExtra;
  /** False for a section the engine wrote — no paragraph is a speaker turn. */
  allowSpeakerTurns?: boolean;
}

/** A note section, typeset: headings, nested bullets, checklists, quotes, small tables. */
export function RichText({
  text,
  placeholder = "Nothing entered.",
  className,
  lineExtra,
  allowSpeakerTurns = true,
}: RichTextProps) {
  const blocks = useMemo(
    () => parseRichText(text, { speakerTurns: allowSpeakerTurns }),
    [text, allowSpeakerTurns],
  );
  if (blocks.length === 0) {
    return <div className={`rt empty-val ${className ?? ""}`}>{placeholder}</div>;
  }
  return (
    <div className={`rt ${className ?? ""}`}>
      <Blocks blocks={blocks} extra={lineExtra} />
    </div>
  );
}
