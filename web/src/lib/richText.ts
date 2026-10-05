/**
 * Markdown-lite → blocks, same grammar as note-service's `pdf_richtext.py` plus nesting.
 * Pure; output is text only (never markup), so React escapes it.
 */

/** One run of inline text with at most one emphasis on it. */
export interface Inline {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
}

export interface ListItem {
  spans: Inline[];
  /** Nesting level, 0 for a top-level bullet. */
  depth: number;
  ordered: boolean;
  /** Set (true/false) only on checklist items. */
  done?: boolean;
  /** The number the author wrote, for ordered items. */
  num?: number;
  /** The source line, marker included — the evidence row key. */
  raw?: string;
}

export type Block =
  | { kind: "heading"; level: number; spans: Inline[] }
  /** `speaker` is set when the paragraph opens with a short `Name:` label — a transcript turn. */
  | { kind: "para"; spans: Inline[]; speaker?: string; raw?: string }
  | { kind: "list"; items: ListItem[] }
  | { kind: "quote"; spans: Inline[] }
  | { kind: "rule" }
  | { kind: "table"; head: Inline[][]; rows: Inline[][][] };

// ── line shapes (the PDF renderer's, with the indent captured) ────────
const HEADING = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/;
const CHECK = /^(\s*)(?:[-*+•])\s*\[([ xX])\]\s+(.*)$/;
const BULLET = /^(\s*)(?:[-*+•‣–])\s+(.*)$/;
const ORDERED = /^(\s*)(\d{1,3})[.)]\s+(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const RULE = /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$/;

/** "Anna: we ship Friday" — a turn label: ≤4 words, no markup, not a URL scheme. */
const SPEAKER = /^(?!https?:)([^\s*_`:][^*_`:]{0,39}?):\s+(?=\S)/;

/** Mostly speaker turns = the transcript (same rule as note-service's shared page). */
export function isTranscript(text: string): boolean {
  const paragraphs = text
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (paragraphs.length < 2) return false;
  const turns = paragraphs.filter((p) => {
    const m = SPEAKER.exec(p);
    return m !== null && (m[1] ?? "").trim().split(/\s+/).length <= 4;
  }).length;
  return turns * 10 >= paragraphs.length * 6;
}

// ── inline shapes ─────────────────────────────────────────────────────
const INLINE = new RegExp(
  [
    "`([^`\\n]+)`", // code
    "\\*\\*(\\S(?:[^*]*\\S)?)\\*\\*", // **bold**
    "(?<![\\w*])\\*(\\S(?:[^*\\n]*\\S)?)\\*(?![\\w*])", // *italic*
    "(?<![\\w_])_(\\S(?:[^_\\n]*\\S)?)_(?![\\w_])", // _italic_
  ].join("|"),
  "g",
);

/** Split one line into runs, marking code, bold and italic. */
export function inlineSpans(text: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  INLINE.lastIndex = 0;
  for (let m = INLINE.exec(text); m !== null; m = INLINE.exec(text)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index) });
    if (m[1] !== undefined) out.push({ text: m[1], code: true });
    else if (m[2] !== undefined) out.push({ text: m[2], bold: true });
    else out.push({ text: m[3] ?? m[4] ?? "", italic: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out.length > 0 ? out : [{ text }];
}

/** How far a line is indented, tabs counting as four columns. */
function indentOf(prefix: string): number {
  return prefix.replace(/\t/g, "    ").length;
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
}

function isTable(lines: string[]): boolean {
  return lines.length >= 2 && (lines[0] ?? "").includes("|") && TABLE_SEP.test(lines[1] ?? "");
}

export interface ParseOptions {
  /** Read "Name: …" paragraphs as turns (default). Off for engine-written sections. */
  speakerTurns?: boolean;
}

/** Single newlines are soft wraps; a blank line starts a new block. */
export function parseRichText(text: string, opts: ParseOptions = {}): Block[] {
  const speakerTurns = opts.speakerTurns ?? true;
  if (!text || !text.trim()) return [];

  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  let items: ListItem[] = [];
  /** Indent columns seen so far in the open list, innermost last. */
  let columns: number[] = [];

  const flushPara = () => {
    const body = para
      .map((l) => l.trim())
      .filter(Boolean)
      .join(" ");
    para = [];
    if (!body) return;
    const turn = speakerTurns ? SPEAKER.exec(body) : null;
    if (turn && (turn[1] ?? "").trim().split(/\s+/).length <= 4) {
      blocks.push({ kind: "para", spans: inlineSpans(body.slice(turn[0].length)), speaker: turn[1] });
      return;
    }
    blocks.push({ kind: "para", spans: inlineSpans(body), raw: body });
  };

  const flushList = () => {
    if (items.length > 0) blocks.push({ kind: "list", items });
    items = [];
    columns = [];
  };

  const flush = () => {
    flushPara();
    flushList();
  };

  /** Depth of an indent in the open list, capped at 4. */
  const depthFor = (indent: number): number => {
    while (columns.length > 0 && indent < (columns[columns.length - 1] as number)) columns.pop();
    if (columns.length === 0 || indent > (columns[columns.length - 1] as number)) columns.push(indent);
    return Math.min(columns.length - 1, 4);
  };

  const push = (item: Omit<ListItem, "depth">, indent: number) => {
    flushPara();
    items.push({ ...item, depth: depthFor(indent) });
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";

    if (!line.trim()) {
      flush();
      continue;
    }

    if (isTable(lines.slice(i))) {
      flush();
      const block: string[] = [];
      for (let row = lines[i]; row !== undefined && row.includes("|") && row.trim(); row = lines[++i]) {
        block.push(row);
      }
      i--;
      const [header, ...body] = block.filter((r) => !TABLE_SEP.test(r));
      blocks.push({
        kind: "table",
        head: splitRow(header ?? "").map(inlineSpans),
        rows: body.map((r) => splitRow(r).map(inlineSpans)),
      });
      continue;
    }

    if (RULE.test(line)) {
      flush();
      blocks.push({ kind: "rule" });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      // h1/h2 belong to the document chrome, so the body starts at h3.
      blocks.push({
        kind: "heading",
        level: Math.min((heading[1] ?? "#").length + 2, 4),
        spans: inlineSpans(heading[2] ?? ""),
      });
      continue;
    }

    const check = CHECK.exec(line);
    if (check) {
      push(
        { spans: inlineSpans(check[3] ?? ""), ordered: false, done: (check[2] ?? "").toLowerCase() === "x", raw: line },
        indentOf(check[1] ?? ""),
      );
      continue;
    }

    const bullet = BULLET.exec(line);
    if (bullet) {
      push({ spans: inlineSpans(bullet[2] ?? ""), ordered: false, raw: line }, indentOf(bullet[1] ?? ""));
      continue;
    }

    const ordered = ORDERED.exec(line);
    if (ordered) {
      push(
        { spans: inlineSpans(ordered[3] ?? ""), ordered: true, num: Number(ordered[2] ?? 1), raw: line },
        indentOf(ordered[1] ?? ""),
      );
      continue;
    }

    const quote = QUOTE.exec(line);
    if (quote) {
      const body = [quote[1] ?? ""];
      while (i + 1 < lines.length) {
        const next = QUOTE.exec(lines[i + 1] ?? "");
        if (next === null) break;
        body.push(next[1] ?? "");
        i++;
      }
      flush();
      blocks.push({ kind: "quote", spans: inlineSpans(body.join(" ")) });
      continue;
    }

    // A continuation line under an open list belongs to its last item.
    const open = items[items.length - 1];
    if (open && /^[ \t]/.test(line)) {
      open.spans = [...open.spans, { text: ` ${line.trim()}` }];
      open.raw = `${open.raw ?? ""} ${line.trim()}`;
      continue;
    }

    flushList();
    para.push(line);
  }

  flush();
  return blocks;
}

/** First real line of a body, markup stripped. */
export function richTextPreview(text: string, limit = 160): string {
  for (const block of parseRichText(text)) {
    if (block.kind === "rule" || block.kind === "table") continue;
    const spans = block.kind === "list" ? block.items[0]?.spans : block.spans;
    const flat = (spans ?? []).map((s) => s.text).join("").trim();
    if (flat) return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
  }
  return "";
}
