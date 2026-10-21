import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, setAccessToken, setSessionListener } from "../src/api/http";
import { GenerationStatus } from "../src/components/GenerationStatus";
import { NoteInstructionsCard, OWN_RULES_HELP } from "../src/components/NoteInstructionsCard";
import { ToasterProvider } from "../src/components/Toaster";

const api = vi.hoisted(() => ({
  getAiInstructions: vi.fn(),
  putAiInstructions: vi.fn(),
  deleteAiInstructions: vi.fn(),
  getNoteInstructions: vi.fn(),
  putNoteInstructions: vi.fn(),
  deleteNoteInstructions: vi.fn(),
}));
vi.mock("../src/api/aiInstructions", () => api);

const TEXT = "Length: short. Four summary sentences at most.\nWording: plain words.";
const DEFAULT_TEXT = "Write what was said, by whom. About {{words}} words in total.";

function instructions(over: Record<string, unknown> = {}) {
  return {
    scope: "workspace",
    version: 2,
    text: TEXT,
    source: "workspace",
    default_text: DEFAULT_TEXT,
    profile: {},
    profile_hash: "",
    compile_status: "compiled",
    compile_error_kind: null,
    understood: [],
    guidance: [],
    not_applied: [],
    can_edit: true,
    max_chars: 12000,
    updated_at: "2026-10-19T10:00:00Z",
    updated_by: "u1",
    ...over,
  };
}

function renderCard() {
  return render(
    <MemoryRouter>
      <ToasterProvider>
        <NoteInstructionsCard />
      </ToasterProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("note instructions card (P2: one text, read verbatim)", () => {
  it("shows a member the text and nothing to edit with", async () => {
    api.getAiInstructions.mockResolvedValue(instructions({ can_edit: false }));
    renderCard();
    expect(await screen.findByText(/Four summary sentences at most/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit|Check|Save|Clear/ })).toBeNull();
    expect(api.getAiInstructions).toHaveBeenCalledTimes(1);
    expect(api.getAiInstructions).toHaveBeenCalledWith();
  });

  it("has no tabs, no readout and no Check: the writer reads the text as it is", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByRole("button", { name: "Check" })).toBeNull();
    expect(screen.queryByText(/Understood|Preview — not saved yet/)).toBeNull();
  });

  it("shows the default rules, labelled, when nothing is saved — and no Reset", async () => {
    api.getAiInstructions.mockResolvedValue(
      instructions({ version: 0, text: DEFAULT_TEXT, source: "default" }),
    );
    renderCard();
    expect(await screen.findByText(/Write what was said, by whom/)).toBeInTheDocument();
    expect(screen.getByTestId("instructions-source")).toHaveTextContent("Default rules");
    expect(screen.queryByRole("button", { name: "Reset to default" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Note instructions" }) as HTMLTextAreaElement;
    // The box holds the default rules themselves, not an empty box with a placeholder.
    expect(box.value).toBe(DEFAULT_TEXT);
    expect(box.placeholder).toBe("");
    expect(box).toHaveAttribute("maxlength", "12000");
    expect(screen.getByText(OWN_RULES_HELP)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("labels a saved text Edited, with its version", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    renderCard();
    await screen.findByText(/Four summary sentences at most/);
    expect(screen.getByTestId("instructions-source")).toHaveTextContent("Edited · v2");
    expect(screen.getByRole("button", { name: "Reset to default" })).toBeInTheDocument();
  });

  it("loads a file into the box and saves nothing until Save", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const file = new File(["# My rules\nShort."], "SKILL.md", { type: "text/markdown" });
    const input = screen.getByLabelText("Instructions file") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    const box = screen.getByRole("textbox", { name: "Note instructions" }) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe("# My rules\nShort."));
    expect(api.putAiInstructions).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("does not save text identical to what is stored", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(api.putAiInstructions).not.toHaveBeenCalled();
  });

  it("saves once with PUT and names the version the server returned", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    api.putAiInstructions.mockResolvedValue(instructions({ version: 3, text: "Plain words." }));
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Plain words." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "Instructions saved (v3). The next note written in this workspace follows them.",
      ),
    ).toBeInTheDocument();
    expect(api.putAiInstructions).toHaveBeenCalledTimes(1);
    expect(api.putAiInstructions).toHaveBeenCalledWith({ text: "Plain words." });
    expect(screen.getByText("Plain words.")).toBeInTheDocument();
  });

  it("resets to the default rules after a confirmation", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    api.deleteAiInstructions.mockResolvedValue(undefined);
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Reset to default" }));
    expect(api.deleteAiInstructions).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog", {
      name: "Replace your instructions with the default rules?",
    });
    expect(dialog).toHaveTextContent("Your text will be lost.");
    api.getAiInstructions.mockResolvedValue(
      instructions({ version: 0, text: DEFAULT_TEXT, source: "default" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(api.deleteAiInstructions).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Write what was said, by whom/)).toBeInTheDocument();
    expect(screen.getByTestId("instructions-source")).toHaveTextContent("Default rules");
  });

  it("is absent while the feature is off, with no toast", async () => {
    api.getAiInstructions.mockRejectedValue(
      new ApiError(404, {
        status: 404,
        code: "not_available",
        detail: "note instructions are not available",
      }),
    );
    const { container } = renderCard();
    await waitFor(() => expect(api.getAiInstructions).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector("section")).toBeNull());
    expect(document.querySelector(".toaster")?.children.length ?? 0).toBe(0);
    expect(screen.queryByText(/not available/)).toBeNull();
  });
});

describe("generation status under instructions", () => {
  beforeEach(() => {
    setSessionListener({});
    setAccessToken("x");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("names the instructions version and links to them", async () => {
    const view = {
      id: "g1",
      status: "complete",
      step: null,
      windows_total: 8,
      windows_done: 8,
      windows_failed: 0,
      failed_ranges: [],
      prompt_version: "2026-10-21",
      model_id: "m",
      error_kind: null,
      created_at: "2026-10-19T10:00:00Z",
      finished_at: "2026-10-19T10:01:00Z",
      suggested_sections: [],
      sections_written: 3,
      instructions: { scope: "workspace", version: 3 },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(view), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    render(
      <MemoryRouter>
        <ToasterProvider>
          <GenerationStatus noteId="n1" />
        </ToasterProvider>
      </MemoryRouter>,
    );
    const link = await screen.findByRole("link", { name: "v3" });
    expect(link).toHaveAttribute("href", "/settings/writing");
    expect(screen.getByText(/Written with workspace instructions/)).toBeInTheDocument();
  });
});

const gen = vi.hoisted(() => ({ regenerate: vi.fn(), getGeneration: vi.fn() }));
vi.mock("../src/api/generation", async (orig) => ({
  ...(await orig<typeof import("../src/api/generation")>()),
  regenerate: gen.regenerate,
}));

describe("write this note differently", () => {
  async function sheet(existing: Record<string, unknown> = {}) {
    const { NoteInstructionsSheet } = await import("../src/components/NoteInstructionsSheet");
    const onRewritten = vi.fn();
    api.getNoteInstructions.mockResolvedValue(
      instructions({ scope: "note", version: 0, text: "", ...existing }),
    );
    render(
      <MemoryRouter>
        <ToasterProvider>
          <NoteInstructionsSheet noteId="n1" onClose={vi.fn()} onRewritten={onRewritten} />
        </ToasterProvider>
      </MemoryRouter>,
    );
    return onRewritten;
  }

  it("saves, then regenerates — and has no Check", async () => {
    const order: string[] = [];
    api.putNoteInstructions.mockImplementation(async () => {
      order.push("put");
      return instructions({ scope: "note", version: 1 });
    });
    gen.regenerate.mockImplementation(async () => {
      order.push("regenerate");
      return { id: "g", status: "queued" };
    });
    const onRewritten = await sheet();
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "One paragraph." } });
    expect(screen.queryByRole("button", { name: "Check" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate this note with the new instructions" }),
    );
    await waitFor(() => expect(onRewritten).toHaveBeenCalled());
    expect(order).toEqual(["put", "regenerate"]);
    expect(api.putNoteInstructions).toHaveBeenCalledWith("n1", { text: "One paragraph." });
    expect(gen.regenerate).toHaveBeenCalledWith("n1");
  });

  it("removes, then rewrites", async () => {
    const order: string[] = [];
    api.deleteNoteInstructions.mockImplementation(async () => void order.push("delete"));
    gen.regenerate.mockImplementation(async () => {
      order.push("regenerate");
      return { id: "g", status: "queued" };
    });
    await sheet({ version: 1, text: "One paragraph." });
    fireEvent.click(await screen.findByRole("button", { name: "Remove and rewrite" }));
    await waitFor(() => expect(order).toEqual(["delete", "regenerate"]));
  });

  it("keeps the text when the rewrite is refused", async () => {
    api.putNoteInstructions.mockResolvedValue(instructions({ scope: "note", version: 1 }));
    gen.regenerate.mockRejectedValue(
      new ApiError(409, { status: 409, code: "generation_in_progress" }),
    );
    await sheet();
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "One paragraph." } });
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate this note with the new instructions" }),
    );
    expect(
      await screen.findByText("Saved; the note could not be rewritten right now."),
    ).toBeInTheDocument();
    expect(api.deleteNoteInstructions).not.toHaveBeenCalled();
  });
});

describe("status wording per scope", () => {
  beforeEach(() => {
    setSessionListener({});
    setAccessToken("x");
  });
  afterEach(() => vi.unstubAllGlobals());

  async function status(instructions: Record<string, unknown>) {
    const view = {
      id: "g1",
      status: "complete",
      step: null,
      windows_total: 2,
      windows_done: 2,
      windows_failed: 0,
      failed_ranges: [],
      prompt_version: "p",
      model_id: "m",
      error_kind: null,
      created_at: "2026-10-19T10:00:00Z",
      finished_at: "2026-10-19T10:01:00Z",
      suggested_sections: [],
      sections_written: 3,
      instructions,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(view), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    const { container } = render(
      <MemoryRouter>
        <ToasterProvider>
          <GenerationStatus noteId="n1" />
        </ToasterProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(container.querySelector(".gen-instructions")).not.toBeNull());
    return container.querySelector(".gen-instructions")!.textContent;
  }

  it("names the meeting type's", async () => {
    expect(await status({ scope: "client", version: 1 })).toContain(
      "Written with client-call instructions v1",
    );
  });
  it("names this note's own", async () => {
    expect(await status({ scope: "note", version: 1 })).toContain(
      "Written with this note's instructions",
    );
  });
});
