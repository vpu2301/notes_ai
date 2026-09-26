import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DocTypePill } from "../src/components/DocTypePill";
import { parseRichText } from "../src/lib/richText";

describe("the document-type pill (Summary Engine v2, Q3)", () => {
  it("says what the recording was when it is not a meeting", () => {
    render(<DocTypePill templateName="Meeting notes" recordingType="podcast_broadcast" />);
    const pill = screen.getByText("Podcast / broadcast");
    expect(pill.closest(".doc-pill")).toHaveAttribute(
      "title",
      "Detected from the recording; change the meeting type to override",
    );
    expect(screen.queryByText("Meeting notes")).not.toBeInTheDocument();
  });

  it("keeps the template's name for a meeting, and before any run", () => {
    const { rerender } = render(<DocTypePill templateName="Meeting notes" recordingType="meeting" />);
    expect(screen.getByText("Meeting notes")).toBeInTheDocument();
    rerender(<DocTypePill templateName="Meeting notes" recordingType={null} />);
    expect(screen.getByText("Meeting notes")).toBeInTheDocument();
  });
});

describe("the rich-text renderer is unchanged", () => {
  it("still reads a user's own 'Hinweis zum Transkript: …' paragraph as a speaker turn", () => {
    // The engine no longer writes such a line (Q3); what a person types
    // is rendered exactly as before.
    const [block] = parseRichText("Hinweis zum Transkript: eine Passage fehlt.");
    expect(block).toMatchObject({ kind: "para", speaker: "Hinweis zum Transkript" });
  });
});
