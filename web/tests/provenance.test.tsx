import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LineEvidence } from "../src/components/EvidencePopover";
import { provenanceLabel } from "../src/i18n/note";
import type { GeneratedItem } from "../src/api/types";

const row: GeneratedItem = {
  item_key: "k1",
  kind: "summary_sentence",
  section_key: "gen:overview",
  text: "Die Abgabe steigt und der Rat tagt am Montag.",
  owner_label: null,
  due_text: null,
  due_date: null,
  explicit: true,
  confidence: 0.9,
  flags: [],
  quote: "die Abgabe steigt im März",
  start_ms: 28_000,
  end_ms: 35_000,
  speaker_label: "SPEAKER_1",
  speaker_name: null,
  placement: "written",
  cites: ["f1", "f2"],
  certainty: null,
  attributed_to: null,
  provenance: "composed",
};

describe("provenance (B4)", () => {
  it("names what a line is, in the note's language", () => {
    expect(provenanceLabel("de", "composed", 2)).toBe("Aus 2 Aussagen");
    expect(provenanceLabel("de", "paraphrase")).toBe("Paraphrase");
    expect(provenanceLabel("uk", "verbatim")).toBe("Дослівно");
    expect(provenanceLabel("en", "composed", 3)).toBe("From 3 statements");
    expect(provenanceLabel("de", null)).toBeNull();
    expect(provenanceLabel(undefined, "verbatim")).toBe("Verbatim");
  });

  it("shows the marker and the verdict in the evidence popover", () => {
    render(<LineEvidence noteId="n1" row={{ ...row, verdict: "widerlegt — die längst widerlegt ist" }} language="de" />);
    fireEvent.click(screen.getByLabelText("Show where this came from"));
    expect(screen.getAllByText("Aus 2 Aussagen").length).toBeGreaterThan(0);
    expect(screen.getByText("widerlegt — die längst widerlegt ist")).toBeTruthy();
    expect(screen.getByText(/00:28/)).toBeTruthy();
  });

  it("shows nothing for a row written before provenance existed", () => {
    render(<LineEvidence noteId="n1" row={{ ...row, provenance: null, cites: ["f1"] }} language="de" />);
    fireEvent.click(screen.getByLabelText("Show where this came from"));
    expect(screen.queryByText(/Aussagen|Paraphrase|Wörtlich/)).toBeNull();
  });
});
