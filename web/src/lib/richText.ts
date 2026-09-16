/**
 * Markdown-lite → blocks, for the note body on screen.
 *
 * A generated note is not flat prose: it arrives as headings, nested
 * bullets, numbered decisions, checkbox action items and bold run-in
 * leads. The PDF has always typeset that (note-service's
 * `domain/pdf_richtext.py`); on screen it was dumped into a `pre-wrap`
 * box, so the reader saw the raw `- ` and `**…**` instead of a document.
 *
 * This parser recognises the same grammar as the PDF one, plus nesting:
 * indentation puts a bullet at a depth, and the renderer draws a
 * different glyph per level.
 *
 * Pure function of the input string — no time, no locale, no DOM. The
 * output carries text only (never markup), so React escapes it for us.
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
}

export type Block =
  | { kind: "heading"; level: number; spans: Inline[] }
  | { kind: "para"; spans: Inline[] }
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

/**
 * Parse one section body into blocks. Single newlines are soft wraps
 * inside a paragraph; a blank line starts a new block — which is how the
 * note editor's plain-text fields behave.
 */
export function parseRichText(text: string): Block[] {
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
    if (body) blocks.push({ kind: "para", spans: inlineSpans(body) });
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

  /** Where an indent sits in the open list — capped so one stray space
      cannot push a bullet three levels deep. */
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
        { spans: inlineSpans(check[3] ?? ""), ordered: false, done: (check[2] ?? "").toLowerCase() === "x" },
        indentOf(check[1] ?? ""),
      );
      continue;
    }

    const bullet = BULLET.exec(line);
    if (bullet) {
      push({ spans: inlineSpans(bullet[2] ?? ""), ordered: false }, indentOf(bullet[1] ?? ""));
      continue;
    }

    const ordered = ORDERED.exec(line);
    if (ordered) {
      push(
        { spans: inlineSpans(ordered[3] ?? ""), ordered: true, num: Number(ordered[2] ?? 1) },
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
      continue;
    }

    flushList();
    para.push(line);
  }

  flush();
  return blocks;
}

/**
 * A one-line preview of a body — the first real sentence, with the
 * markup stripped. Used where a note is summarised rather than read.
 */
export function richTextPreview(text: string, limit = 160): string {
  for (const block of parseRichText(text)) {
    if (block.kind === "rule" || block.kind === "table") continue;
    const spans = block.kind === "list" ? block.items[0]?.spans : block.spans;
    const flat = (spans ?? []).map((s) => s.text).join("").trim();
    if (flat) return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
  }
  return "";
}
