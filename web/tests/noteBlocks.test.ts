import { describe, expect, it } from "vitest";
import type { NoteContent, TemplateSection } from "../src/api/types";
import { noteBlocks } from "../src/lib/noteBlocks";

const MEETING: TemplateSection[] = [
  { id: "user_notes", name: "My notes", field_type: "free_text", order: 0 },
  { id: "attendees", name: "Attendees", field_type: "free_text", required: true, order: 1 },
  { id: "discussion", name: "Discussion", field_type: "free_text", required: true, order: 2 },
  { id: "decisions", name: "Decisions", field_type: "free_text", order: 3 },
  { id: "action_items", name: "Action items", field_type: "free_text", required: true, order: 4 },
];

const content = (sections: NoteContent["sections"]): NoteContent => ({
  template_id: "t1",
  template_schema_version: 1,
  sections,
});

const shape = (blocks: ReturnType<typeof noteBlocks>) => blocks.map((b) => [b.key, b.title]);

describe("note blocks: structure follows content", () => {
  it("Test A/D — a simple note is its text, with no heading and no template sections", () => {
    const blocks = noteBlocks(content([{ section_key: "user_notes", text: "Call Peter tomorrow." }]), MEETING, {
      editable: true,
    });
    expect(shape(blocks)).toEqual([["user_notes", null]]);
    expect(blocks[0]?.section.text).toBe("Call Peter tomorrow.");
  });

  it("Test E — an empty template section never becomes an empty heading", () => {
    const seeded = MEETING.map((d) => ({ section_key: d.id, text: "" }));
    // Read-only: nothing at all.
    expect(noteBlocks(content(seeded), MEETING, { editable: false })).toEqual([]);
    // Editable: only the pad, unheaded.
    expect(shape(noteBlocks(content(seeded), MEETING, { editable: true }))).toEqual([["user_notes", null]]);
  });

  it("Test C — engine-made sections carry their own titles; the opening block has none", () => {
    const blocks = noteBlocks(
      content([
        { section_key: "user_notes", text: "" },
        { section_key: "gen:overview", text: "Interview about the club." },
        { section_key: "gen:squad-development", title: "Squad development", text: "- one" },
        { section_key: "gen:transfers", title: "Transfer strategy", text: "- two" },
        { section_key: "decisions", text: "- agreed" },
        { section_key: "attendees", text: "" },
      ]),
      MEETING,
      { editable: false },
    );
    expect(shape(blocks)).toEqual([
      ["gen:overview", null],
      ["gen:squad-development", "Squad development"],
      ["gen:transfers", "Transfer strategy"],
      ["decisions", "Decisions"],
    ]);
  });

  it("Test B — a single-topic note is one unheaded block", () => {
    const blocks = noteBlocks(content([{ section_key: "gen:overview", text: "One coherent subject." }]), MEETING, {
      editable: false,
    });
    expect(shape(blocks)).toEqual([["gen:overview", null]]);
  });

  it("keeps the transcript behind its own tab", () => {
    const blocks = noteBlocks(
      content([{ section_key: "discussion", text: "Speaker 1: hello\n\nSpeaker 2: hi there" }]),
      MEETING,
      { editable: false },
    );
    expect(blocks).toEqual([]);
  });

  it("Test F — a legacy form template keeps its fields while editable, and only those with text otherwise", () => {
    const legacy: TemplateSection[] = [
      { id: "findings", name: "Findings", field_type: "free_text", order: 1 },
      { id: "impression", name: "Impression", field_type: "free_text", order: 2 },
      { id: "target_date", name: "Target date", field_type: "date", order: 3 },
    ];
    const c = content([
      { section_key: "findings", text: "LV function improved to 49%." },
      { section_key: "impression", text: "" },
    ]);
    expect(shape(noteBlocks(c, legacy, { editable: true }))).toEqual([
      ["findings", "Findings"],
      ["impression", "Impression"],
      ["target_date", "Target date"],
    ]);
    expect(shape(noteBlocks(c, legacy, { editable: false }))).toEqual([["findings", "Findings"]]);
  });

  it("a typed field stays reachable while editable even when empty", () => {
    const defs: TemplateSection[] = [
      ...MEETING,
      { id: "deal_stage", name: "Deal stage", field_type: "choice", order: 9 },
    ];
    const blocks = noteBlocks(content([{ section_key: "user_notes", text: "" }]), defs, { editable: true });
    expect(shape(blocks)).toEqual([
      ["user_notes", null],
      ["deal_stage", "Deal stage"],
    ]);
  });
});
