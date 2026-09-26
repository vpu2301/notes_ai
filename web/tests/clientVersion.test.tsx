import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CarriedItems } from "../src/components/CarriedItems";
import { ClientVersionPanel } from "../src/components/ClientVersion";
import { ToasterProvider } from "../src/components/Toaster";

const notes = vi.hoisted(() => ({
  getClientVersion: vi.fn(),
  getClientVersionCheck: vi.fn(),
  getCarried: vi.fn(),
  setCarriedState: vi.fn(),
}));
vi.mock("../src/api/notes", async (orig) => ({
  ...(await orig<typeof import("../src/api/notes")>()),
  ...notes,
}));

function wrap(node: React.ReactNode) {
  return render(<ToasterProvider>{node}</ToasterProvider>);
}

beforeEach(() => {
  notes.getClientVersion.mockReset().mockResolvedValue({
    available: true,
    reason: null,
    title: "Acme weekly",
    sections: [
      { section_key: "decisions", role: "decisions", name: "Decisions", text: "- Ship on the 20th" },
    ],
    hidden_lines: 2,
    hidden_sections: ["user_notes", "transcript"],
  });
  notes.getClientVersionCheck.mockReset().mockResolvedValue({
    available: true,
    warnings: [
      { code: "internal_lines_hidden", detail: "Lines you marked internal are not in the client version.", count: 2 },
    ],
    is_empty: false,
  });
  notes.getCarried.mockReset().mockResolvedValue({
    items: [
      {
        item_key: "k1",
        text: "send the brand assets",
        owner_label: "Tom",
        due_text: "the 20th",
        state: "open",
      },
      {
        item_key: "k2",
        text: "confirm the budget",
        owner_label: "Anna",
        due_text: null,
        state: "done_mentioned",
        done_quote: "we sent the assets on Monday",
        done_speaker: "Tom",
      },
    ],
    from_note_id: "note-1",
    from_note_code: "N-12",
    from_date: "2026-09-12",
  });
  notes.setCarriedState.mockReset().mockResolvedValue({ item_key: "k1", state: "done_marked" });
});
afterEach(() => vi.clearAllMocks());

describe("the client version shows what a client gets", () => {
  it("renders the document the server built", async () => {
    wrap(<ClientVersionPanel noteId="n1" />);
    expect(await screen.findByText("Acme weekly")).toBeInTheDocument();
    expect(screen.getByText("Decisions")).toBeInTheDocument();
    expect(screen.getByText(/Ship on the 20th/)).toBeInTheDocument();
  });

  it("says what stayed behind, without showing it", async () => {
    wrap(<ClientVersionPanel noteId="n1" />);
    await screen.findByText("Acme weekly");
    expect(screen.getByText(/Lines you marked internal/)).toBeInTheDocument();
    // The preview must never leak the very thing it is hiding.
    expect(screen.queryByText(/ask about budget/)).toBeNull();
  });

  it("does not pretend a 1:1 has a client version", async () => {
    notes.getClientVersion.mockRejectedValue(
      new Error("a one-to-one and an interview debrief have no client version"),
    );
    wrap(<ClientVersionPanel noteId="n1" />);
    expect(await screen.findByText(/no client version/)).toBeInTheDocument();
  });

  it("says so when there would be nothing to send", async () => {
    notes.getClientVersion.mockResolvedValue({
      available: true,
      reason: null,
      title: "Acme weekly",
      sections: [],
      hidden_lines: 0,
      hidden_sections: ["user_notes"],
    });
    wrap(<ClientVersionPanel noteId="n1" />);
    expect(await screen.findByText(/nothing a client could read/)).toBeInTheDocument();
  });
});

describe("still open from last time", () => {
  it("lists the previous meeting's open items and links to it", async () => {
    wrap(<CarriedItems noteId="n2" />);
    // The date is formatted in the viewer's locale, so match the phrase
    // and the day rather than one locale's ordering.
    const head = await screen.findByRole("heading", { name: /Still open from/ });
    expect(head).toHaveTextContent("12");
    expect(head).toHaveTextContent("Sep");
    expect(screen.getByText(/send the brand assets/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "N-12" })).toHaveAttribute("href", "/notes/note-1");
  });

  it("shows the words that say an item was done", async () => {
    wrap(<CarriedItems noteId="n2" />);
    expect(await screen.findByText(/we sent the assets on Monday/)).toBeInTheDocument();
  });

  it("ticks an item off", async () => {
    wrap(<CarriedItems noteId="n2" />);
    await screen.findByText(/send the brand assets/);
    const boxes = screen.getAllByRole("checkbox");
    fireEvent.click(boxes[0]!);
    await waitFor(() =>
      expect(notes.setCarriedState).toHaveBeenCalledWith("n2", "k1", "done_marked"),
    );
  });

  it("drops an item", async () => {
    wrap(<CarriedItems noteId="n2" />);
    fireEvent.click(await screen.findByRole("button", { name: /Drop send the brand assets/ }));
    await waitFor(() =>
      expect(notes.setCarriedState).toHaveBeenCalledWith("n2", "k1", "dropped"),
    );
  });

  it("puts a failed tick back rather than lying about it", async () => {
    notes.setCarriedState.mockRejectedValue(new Error("nope"));
    wrap(<CarriedItems noteId="n2" />);
    await screen.findByText(/send the brand assets/);
    const box = screen.getAllByRole("checkbox")[0]!;
    fireEvent.click(box);
    await waitFor(() => expect(box).not.toBeChecked());
  });

  it("shows nothing at all when this meeting is not part of a series", async () => {
    notes.getCarried.mockResolvedValue({
      items: [],
      from_note_id: null,
      from_note_code: null,
      from_date: null,
    });
    const { container } = wrap(<CarriedItems noteId="n2" />);
    await waitFor(() => expect(notes.getCarried).toHaveBeenCalled());
    expect(container.querySelector(".carried")).toBeNull();
  });

  it("stays quiet when the previous note is no longer readable", async () => {
    notes.getCarried.mockRejectedValue(new Error("404"));
    const { container } = wrap(<CarriedItems noteId="n2" />);
    await waitFor(() => expect(notes.getCarried).toHaveBeenCalled());
    expect(container.querySelector(".carried")).toBeNull();
  });

  it("is read-only on a note this person cannot edit", async () => {
    wrap(<CarriedItems noteId="n2" readOnly />);
    await screen.findByText(/send the brand assets/);
    expect(screen.getAllByRole("checkbox")[0]).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Drop/ })).toBeNull();
  });
});
