import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AskNote } from "../src/components/AskNote";
import { ToasterProvider } from "../src/components/Toaster";

const notes = vi.hoisted(() => ({ askNote: vi.fn() }));
vi.mock("../src/api/notes", async (orig) => ({
  ...(await orig<typeof import("../src/api/notes")>()),
  ...notes,
}));

/** The page's side of the contract: it counts the thread and can clear it. */
function Host({ onCount }: { onCount: (n: number) => void }) {
  const [reset, setReset] = useState(0);
  return (
    <ToasterProvider>
      <button onClick={() => setReset((k) => k + 1)}>Clear chat</button>
      <AskNote noteId="n1" resetKey={reset} onThreadChange={onCount} />
    </ToasterProvider>
  );
}

beforeEach(() => {
  notes.askNote.mockReset().mockResolvedValue({ answer: "Tuesday, per the decisions section." });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.clearAllMocks());

describe("the ask thread and the ⋯ menu", () => {
  it("reports the thread size and clears on request", async () => {
    const onCount = vi.fn();
    render(<Host onCount={onCount} />);
    expect(onCount).toHaveBeenLastCalledWith(0);

    fireEvent.change(screen.getByLabelText("Ask about this note"), { target: { value: "When do we ship?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Tuesday, per the decisions section.");
    expect(onCount).toHaveBeenLastCalledWith(2);
    expect(notes.askNote).toHaveBeenCalledWith("n1", "When do we ship?", []);

    fireEvent.click(screen.getByRole("button", { name: "Clear chat" }));
    await waitFor(() => expect(screen.queryByText("When do we ship?")).toBeNull());
    expect(onCount).toHaveBeenLastCalledWith(0);
  });
});
