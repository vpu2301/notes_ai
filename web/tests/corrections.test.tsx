import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EntityCorrection } from "../src/api/types";
import { correctionsBanner, unifiedFromTitle, unifiedParts } from "../src/lib/corrections";

const api = vi.hoisted(() => ({ decideCorrection: vi.fn(), listCorrections: vi.fn(), rememberTerm: vi.fn() }));
vi.mock("../src/api/asr", () => ({ decideCorrection: api.decideCorrection, listCorrections: api.listCorrections }));
vi.mock("../src/api/glossary", () => ({ rememberTerm: api.rememberTerm }));

import { EntityReviewSheet } from "../src/components/EntityReviewSheet";

function corr(over: Partial<EntityCorrection> = {}): EntityCorrection {
  return {
    id: "c1",
    kind: "entity",
    from_forms: ["Andala", "Handela"],
    to_text: "Handala",
    occurrences_count: 3,
    source: "majority",
    confidence: 0.85,
    status: "accepted",
    ...over,
  };
}

describe("the spelling banner (Sprint TQ3)", () => {
  it("says nothing when nothing was unified or proposed", () => {
    expect(correctionsBanner(undefined, "de")).toBeNull();
    expect(correctionsBanner([corr({ status: "rejected" })], "de")).toBeNull();
  });

  it("counts the variant spellings an applied correction replaced", () => {
    expect(correctionsBanner([corr(), corr({ id: "c2", from_forms: ["Welcherung"], to_text: "Welchering" })], "de")).toEqual({
      text: "3 Schreibweisen vereinheitlicht",
      action: "Prüfen",
    });
  });

  it("says what is waiting for review, and both together", () => {
    expect(correctionsBanner([corr({ status: "proposed" })], "en")?.text).toBe("2 spellings to review");
    expect(
      correctionsBanner([corr(), corr({ id: "c2", status: "proposed", from_forms: ["Tilda"], to_text: "Thiel" })], "en")?.text,
    ).toBe("2 spellings unified · 1 spelling to review");
    expect(correctionsBanner([corr()], "uk")?.text).toBe("Уніфіковано написань: 2");
  });
});

describe("the underline", () => {
  it("marks each accepted spelling as a whole word, with where it came from", () => {
    const parts = unifiedParts("Heute über Handala, nicht Handalas Bild.", [corr()]);
    expect(parts.map((p) => [p.text, Boolean(p.correction)])).toEqual([
      ["Heute über ", false],
      ["Handala", true],
      [", nicht Handalas Bild.", false],
    ]);
    expect(unifiedFromTitle(corr(), "de")).toBe("vereinheitlicht aus: Andala, Handela");
  });

  it("leaves a paragraph alone when only proposals exist", () => {
    expect(unifiedParts("Heute über Handela.", [corr({ status: "proposed" })])).toEqual([{ text: "Heute über Handela." }]);
  });
});

describe("the review sheet", () => {
  it("rejecting sends the rev it saw and hands the new view back", async () => {
    const view = { job_id: "j", corrections_rev: 2, corrections: [corr({ status: "rejected" })] };
    api.decideCorrection.mockResolvedValueOnce(view);
    const onChanged = vi.fn();
    render(<EntityReviewSheet jobId="j" corrections={[corr()]} rev={1} online onChanged={onChanged} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(view));
    expect(api.decideCorrection).toHaveBeenCalledWith("j", "c1", { status: "rejected", corrections_rev: 1 });
  });

  it("accepting a glossary spelling teaches the glossary its variants", async () => {
    api.decideCorrection.mockResolvedValueOnce({ job_id: "j", corrections_rev: 2, corrections: [] });
    api.rememberTerm.mockResolvedValueOnce({});
    render(
      <EntityReviewSheet
        jobId="j"
        corrections={[corr({ status: "proposed", source: "glossary" })]}
        rev={1}
        online
        onChanged={() => undefined}
        onClose={() => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(api.rememberTerm).toHaveBeenCalledWith({ term: "Handala", kind: "term", heard_as: ["Andala", "Handela"] }),
    );
  });

  it("is read-only offline", () => {
    render(<EntityReviewSheet jobId="j" corrections={[corr()]} rev={1} online={false} onChanged={() => undefined} onClose={() => undefined} />);
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByText("Offline — reviewing needs a connection.")).toBeInTheDocument();
  });
});
