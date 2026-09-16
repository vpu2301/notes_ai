import { describe, expect, it } from "vitest";
import { inlineSpans, parseRichText, richTextPreview } from "../src/lib/richText";

/** The flat text of a block, ignoring where the emphasis fell. */
function flat(spans: { text: string }[]): string {
  return spans.map((s) => s.text).join("");
}

describe("parseRichText", () => {
  it("gives an empty body no blocks", () => {
    expect(parseRichText("")).toEqual([]);
    expect(parseRichText("   \n\n  ")).toEqual([]);
  });

  it("joins soft-wrapped lines into one paragraph and splits on a blank line", () => {
    const blocks = parseRichText("one\ntwo\n\nthree");
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ kind: "para" });
    expect(flat((blocks[0] as { spans: { text: string }[] }).spans)).toBe("one two");
    expect(flat((blocks[1] as { spans: { text: string }[] }).spans)).toBe("three");
  });

  it("starts body headings at h3 — h1 and h2 are the document's own", () => {
    const blocks = parseRichText("# Top\n## Under\n###### Deep");
    expect(blocks.map((b) => (b as { level: number }).level)).toEqual([3, 4, 4]);
  });

  it("reads indentation as nesting", () => {
    const blocks = parseRichText(["- one", "  - two", "    - three", "- back"].join("\n"));
    expect(blocks).toHaveLength(1);
    const list = blocks[0] as { kind: "list"; items: { depth: number }[] };
    expect(list.kind).toBe("list");
    expect(list.items.map((i) => i.depth)).toEqual([0, 1, 2, 0]);
  });

  it("does not let a stray indent open a level of its own", () => {
    // A one-space jog is the same level as far as the reader is concerned;
    // what matters is that it comes back out again on the next line.
    const list = parseRichText("- one\n   - two\n- three").at(0) as { items: { depth: number }[] };
    expect(list.items.map((i) => i.depth)).toEqual([0, 1, 0]);
  });

  it("keeps bullets, numbers and checkboxes apart within one run", () => {
    const list = parseRichText("- a\n1. b\n- [x] c\n- [ ] d").at(0) as {
      items: { ordered: boolean; done?: boolean }[];
    };
    expect(list.items.map((i) => [i.ordered, i.done])).toEqual([
      [false, undefined],
      [true, undefined],
      [false, true],
      [false, false],
    ]);
  });

  it("hangs a continuation line off the item above it", () => {
    const list = parseRichText("- decision\n  agreed with Denys").at(0) as {
      items: { spans: { text: string }[] }[];
    };
    expect(list.items).toHaveLength(1);
    expect(flat(list.items[0]!.spans)).toBe("decision agreed with Denys");
  });

  it("tells a rule from a bullet", () => {
    expect(parseRichText("---").map((b) => b.kind)).toEqual(["rule"]);
    expect(parseRichText("- one").map((b) => b.kind)).toEqual(["list"]);
  });

  it("folds a run of quoted lines into one quote", () => {
    const blocks = parseRichText("> first\n> second");
    expect(blocks).toHaveLength(1);
    expect(flat((blocks[0] as { spans: { text: string }[] }).spans)).toBe("first second");
  });

  it("reads a pipe table, dropping the dashed row", () => {
    const table = parseRichText("| a | b |\n| --- | --- |\n| 1 | 2 |").at(0) as {
      kind: string;
      head: { text: string }[][];
      rows: { text: string }[][][];
    };
    expect(table.kind).toBe("table");
    expect(table.head.map(flat)).toEqual(["a", "b"]);
    expect(table.rows.map((r) => r.map(flat))).toEqual([["1", "2"]]);
  });

  it("carries a heading's text through unescaped — React does the escaping", () => {
    const blocks = parseRichText("# <script>alert(1)</script>");
    expect(flat((blocks[0] as { spans: { text: string }[] }).spans)).toBe("<script>alert(1)</script>");
  });
});

describe("inlineSpans", () => {
  it("marks code, bold and italic and leaves the rest plain", () => {
    expect(inlineSpans("plain **bold** and *soft* and `code`")).toEqual([
      { text: "plain " },
      { text: "bold", bold: true },
      { text: " and " },
      { text: "soft", italic: true },
      { text: " and " },
      { text: "code", code: true },
    ]);
  });

  it("leaves an underscore inside a word alone", () => {
    expect(inlineSpans("note_service_id")).toEqual([{ text: "note_service_id" }]);
  });

  it("leaves an unclosed marker as text", () => {
    expect(inlineSpans("**not closed")).toEqual([{ text: "**not closed" }]);
  });
});

describe("richTextPreview", () => {
  it("takes the first line with words in it, without its markup", () => {
    expect(richTextPreview("## Heading\n- **Vertical 1**: comms")).toBe("Heading");
    expect(richTextPreview("- **Vertical 1**: comms")).toBe("Vertical 1: comms");
  });

  it("trims to the limit", () => {
    expect(richTextPreview("x".repeat(300), 10)).toBe(`${"x".repeat(9)}…`);
  });

  it("has nothing to say about an empty body", () => {
    expect(richTextPreview("")).toBe("");
  });
});
