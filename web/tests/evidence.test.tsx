import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setSessionListener } from "../src/api/http";
import type { GeneratedItem } from "../src/api/types";
import { CorrectionsPanel, correctionsOf } from "../src/components/CorrectionsPanel";
import { CLIP_PADDING_MS, LineEvidence, chipLabel } from "../src/components/EvidencePopover";
import { RichText } from "../src/components/RichText";
import { lineKey } from "../src/lib/itemKey";
import { DetailToggle, uncitedBySection } from "../src/pages/NoteEditorPage";

const ROW: GeneratedItem = {
  item_key: lineKey("- Das Aus für die Rente mit 63 wird abgeschwächt — laut Reinbold"),
  kind: "key_point",
  section_key: "gen:rente",
  text: "Das Aus für die Rente mit 63 wird abgeschwächt — laut Reinbold",
  owner_label: null,
  due_text: null,
  due_date: null,
  explicit: false,
  confidence: 0.7,
  flags: [],
  quote: "das Aus für die Rente mit 63 wird wohl abgeschwächt",
  start_ms: 45_000,
  end_ms: 52_000,
  speaker_label: "SPEAKER_2",
  speaker_name: "Fabian Reinbold",
  placement: "written",
  cites: ["f1", "f2"],
  certainty: "prediction",
  attributed_to: "Fabian Reinbold",
  corrections: [{ surface: "Fabian Reinbolt", canonical: "Fabian Reinbold", source: "candidate" }],
  mentions: [],
};

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  setSessionListener({});
  setAccessToken("x");
});
afterEach(() => vi.unstubAllGlobals());

describe("evidence on a generated line", () => {
  it("opens the quote, the moment and the speaker", () => {
    render(<LineEvidence noteId="n1" row={ROW} />);
    fireEvent.click(screen.getByRole("button", { name: "Show where this came from" }));
    const dialog = screen.getByRole("dialog", { name: "Evidence" });
    expect(dialog).toHaveTextContent("das Aus für die Rente mit 63 wird wohl abgeschwächt");
    expect(dialog).toHaveTextContent("00:45 · Fabian Reinbold");
    expect(dialog).toHaveTextContent("and 1 more");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("plays the recording around the quote", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, body: JSON.parse(String(init?.body ?? "{}")) });
        return respond(200, { clip_id: "c1", clip_url: "/v1/audio-clips/c1?t=tok", expires_at_unix: 1 });
      }),
    );
    const play = vi.fn(async () => undefined);
    vi.stubGlobal("Audio", vi.fn(() => ({ play })));
    render(<LineEvidence noteId="n1" row={ROW} />);
    fireEvent.click(screen.getByRole("button", { name: "Show where this came from" }));
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(calls[0]?.url).toContain("/v1/audio-clips");
    expect(calls[0]?.body).toEqual({
      note_id: "n1",
      start_ms: ROW.start_ms - CLIP_PADDING_MS,
      end_ms: ROW.end_ms + CLIP_PADDING_MS,
    });
  });

  it("says so when the recording is gone", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(410, { code: "audio_purged", title: "gone" })));
    render(<LineEvidence noteId="n1" row={ROW} />);
    fireEvent.click(screen.getByRole("button", { name: "Show where this came from" }));
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(await screen.findByText("Recording no longer available")).toBeInTheDocument();
  });

  it("labels a forecast with whose it is, and shows what a name was heard as", () => {
    expect(chipLabel(ROW)).toBe("Forecast · Reinbold");
    expect(chipLabel({ ...ROW, certainty: "fact" })).toBeNull();
    render(<LineEvidence noteId="n1" row={ROW} />);
    expect(screen.getByText("Forecast · Reinbold")).toBeInTheDocument();
    expect(screen.getByText("Fabian Reinbold")).toHaveAttribute("title", "heard as: Fabian Reinbolt");
  });

  it("offers a calendar file on a key date", () => {
    render(<LineEvidence noteId="n1" row={{ ...ROW, kind: "date", certainty: null }} />);
    expect(screen.getByRole("button", { name: "Add to calendar" })).toBeInTheDocument();
  });

  it("draws evidence only on lines that have a row", () => {
    const text = `- ${ROW.text}\n- A line a person typed`;
    render(
      <RichText
        text={text}
        lineExtra={(raw) => (lineKey(raw) === ROW.item_key ? <LineEvidence noteId="n1" row={ROW} /> : null)}
      />,
    );
    expect(screen.getAllByRole("button", { name: "Show where this came from" })).toHaveLength(1);
  });
});

describe("short, standard, detailed", () => {
  it("is a choice of three and says which is on", () => {
    const picked: string[] = [];
    render(<DetailToggle value="standard" onChange={(v) => picked.push(v)} />);
    expect(screen.getByRole("radio", { name: "Standard" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("radio", { name: "Detailed" }));
    expect(picked).toEqual(["detailed"]);
  });

  it("detailed lists the verified facts no line used, under their topic", () => {
    const unused = { ...ROW, item_key: "u1", text: "Unused fact", placement: "suggested", kind: "key_point", cites: ["u1"] };
    const shown = { ...ROW, placement: "written" };
    const content = { sections: [{ section_key: "gen:rente", text: `- ${ROW.text}` }] };
    const map = uncitedBySection([shown, unused], content);
    expect(map.get("gen:rente")?.map((r) => r.text)).toEqual(["Unused fact"]);
  });

  it("never lists a copied fact kept as evidence (F2)", () => {
    const copy = { ...ROW, item_key: "c1", text: "this boat is incredible", placement: "evidence", cites: ["c1"] };
    const content = { sections: [{ section_key: "gen:rente", text: `- ${ROW.text}` }] };
    expect(uncitedBySection([{ ...ROW }, copy], content).size).toBe(0);
  });
});

describe("the evidence mark is not text (F2)", () => {
  it("the toggle carries no characters a copy could pick up", () => {
    render(<LineEvidence noteId="n1" row={ROW} />);
    const toggle = screen.getByRole("button", { name: "Show where this came from" });
    expect(toggle.textContent?.trim()).toBe("");
    expect(document.body.textContent).not.toContain("❝");
  });

  it("an evidence row resolves a cited fact in the popover", () => {
    const copy = { ...ROW, item_key: "f2", text: "the platform drops into the water", placement: "evidence" };
    render(<LineEvidence noteId="n1" row={ROW} rowsByKey={new Map([["f2", copy]])} />);
    fireEvent.click(screen.getByRole("button", { name: "Show where this came from" }));
    expect(screen.getByRole("dialog", { name: "Evidence" })).toHaveTextContent("the platform drops into the water");
  });
});

describe("sub-points (F2)", () => {
  it("a bullet's children render nested under it", () => {
    const { container } = render(
      <RichText text={"- The swim platform combines both designs\n  - Fixed platform at the transom\n  - Submersible centre section"} />,
    );
    const nested = container.querySelectorAll("li li");
    expect(Array.from(nested).map((li) => li.textContent)).toEqual([
      "Fixed platform at the transom",
      "Submersible centre section",
    ]);
  });
});

describe("names in the note", () => {
  it("collects respelled and doubted names once each", () => {
    const doubted = { ...ROW, item_key: "d1", text: "Emil (?) kommentiert die Entscheidung", corrections: [] };
    const { fixed, doubted: marked } = correctionsOf([ROW, ROW, doubted]);
    expect(fixed).toHaveLength(1);
    expect(marked).toEqual(["Emil"]);
  });

  it("accept adds a glossary term, then records the choice", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method} ${new URL(url).pathname} ${init?.body ?? ""}`);
        return respond(200, { item_key: ROW.item_key, version_number: 1, line: null, id: "t", term: "x" });
      }),
    );
    render(<CorrectionsPanel noteId="n1" rows={[ROW]} version={1} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(await screen.findByText("Added to the glossary")).toBeInTheDocument();
    expect(calls[0]).toContain("POST /v1/glossary");
    expect(calls[0]).toContain('"heard_as":["Fabian Reinbolt"]');
    expect(calls[1]).toContain(`PATCH /v1/notes/n1/items/by-key/${ROW.item_key}`);
    expect(calls[1]).toContain("correction_accepted");
  });

  it("reject puts the heard name back and reloads the note", async () => {
    const reloaded = vi.fn();
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        calls.push(String(init?.body ?? ""));
        return respond(200, { item_key: "k2", version_number: 2, line: "- …" });
      }),
    );
    render(<CorrectionsPanel noteId="n1" rows={[ROW]} version={1} onChanged={reloaded} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Put back as heard")).toBeInTheDocument();
    expect(calls[0]).toContain('"action":"correction_rejected"');
    expect(calls[0]).toContain('"reason":"wrong_name"');
    expect(reloaded).toHaveBeenCalled();
  });
});

describe("figures (F3)", () => {
  it("a specifications table renders as a table, value cells as spoken", () => {
    render(
      <RichText
        text={"| Quantity | Value |\n|---|---|\n| Length overall | 66 feet |\n| Water tank | just under 300 gallons |"}
      />,
    );
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("Length overall");
    expect(table).toHaveTextContent("just under 300 gallons");
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("a figure row carries its verified fields", () => {
    const row: GeneratedItem = {
      ...ROW,
      kind: "figure",
      figure: { name: "Water tank", value: "300", unit: "gallons", qualifier: "just under" },
    };
    expect(row.figure?.qualifier).toBe("just under");
  });
});
