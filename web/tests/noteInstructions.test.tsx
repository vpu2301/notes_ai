import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, setAccessToken, setSessionListener } from "../src/api/http";
import { GenerationStatus } from "../src/components/GenerationStatus";
import { NoteInstructionsCard } from "../src/components/NoteInstructionsCard";
import { ToasterProvider } from "../src/components/Toaster";
import { PRESETS } from "../src/components/noteInstructionsPresets";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const FIXTURES = resolve(__dirname, "../../services/note-service/tests/fixtures/instructions");

const api = vi.hoisted(() => ({
  getAiInstructions: vi.fn(),
  putAiInstructions: vi.fn(),
  previewAiInstructions: vi.fn(),
  deleteAiInstructions: vi.fn(),
  getNoteInstructions: vi.fn(),
  putNoteInstructions: vi.fn(),
  previewNoteInstructions: vi.fn(),
  deleteNoteInstructions: vi.fn(),
}));
vi.mock("../src/api/aiInstructions", () => api);

const TEXT = "# Length\nShort. Four summary sentences at most.\nAlways write in English.";
// The server's sentence, verbatim; the card must not have its own.
const LANGUAGE_MESSAGE = "Notes are written in the language spoken in the meeting.";

function instructions(over: Record<string, unknown> = {}) {
  return {
    scope: "workspace",
    version: 2,
    text: TEXT,
    profile: {},
    profile_hash: "h",
    compile_status: "compiled",
    compile_error_kind: null,
    understood: ["Shorter than standard — about 60 % of the usual length."],
    guidance: [],
    not_applied: [
      { text: "Always write in English", reason: "language_locked", message: LANGUAGE_MESSAGE },
    ],
    can_edit: true,
    max_chars: 8000,
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

describe("note instructions card", () => {
  it("shows a member the text and readout, and nothing to edit with", async () => {
    api.getAiInstructions.mockResolvedValue(instructions({ can_edit: false }));
    renderCard();
    expect(await screen.findByText(/Shorter than standard/)).toBeInTheDocument();
    expect(screen.getByText(/Four summary sentences at most/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Edit|Check|Save|Clear|Copy an example/ }),
    ).toBeNull();
    expect(api.getAiInstructions).toHaveBeenCalledTimes(1);
    expect(api.previewAiInstructions).not.toHaveBeenCalled();
  });

  it("shows each not-applied request with the server's message", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    renderCard();
    expect(
      await screen.findByText(`“Always write in English” — ${LANGUAGE_MESSAGE}`),
    ).toBeInTheDocument();
  });

  it("checks without saving, and Cancel brings the stored readout back", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    api.previewAiInstructions.mockResolvedValue(
      instructions({ understood: ["No figure tables."], not_applied: [] }),
    );
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "No figure tables." } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("Preview — not saved yet")).toBeInTheDocument();
    expect(screen.getByText("No figure tables.", { selector: "li" })).toBeInTheDocument();
    expect(api.previewAiInstructions).toHaveBeenCalledTimes(1);
    expect(api.previewAiInstructions).toHaveBeenCalledWith(
      { text: "No figure tables." },
      "workspace",
    );
    expect(api.putAiInstructions).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("Preview — not saved yet")).not.toBeInTheDocument();
    expect(screen.getByText(/Shorter than standard/)).toBeInTheDocument();
  });

  it("does not save text identical to what is stored", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(api.putAiInstructions).not.toHaveBeenCalled();
  });

  it("saves once and names the version the server returned", async () => {
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
    expect(api.putAiInstructions).toHaveBeenCalledWith({ text: "Plain words." }, "workspace");
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

  it("says when the saved text could not be read, and Try again saves it again", async () => {
    api.getAiInstructions.mockResolvedValue(
      instructions({ compile_status: "failed", understood: [], not_applied: [] }),
    );
    api.putAiInstructions.mockResolvedValue(instructions());
    renderCard();
    expect(await screen.findByText(/could not be read right now/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(api.putAiInstructions).toHaveBeenCalledWith({ text: TEXT }, "workspace"),
    );
  });

  it("names the wait when checks are rate-limited", async () => {
    api.getAiInstructions.mockResolvedValue(instructions());
    api.previewAiInstructions.mockRejectedValue(
      new ApiError(429, { status: 429, code: "too_many_previews", retry_after: 30 }),
    );
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("Too many checks — try again in 30 s.")).toBeInTheDocument();
  });

  it("fills an example and checks it, never saving it", async () => {
    api.getAiInstructions.mockResolvedValue(
      instructions({ version: 0, text: "", understood: [], not_applied: [] }),
    );
    api.previewAiInstructions.mockResolvedValue(instructions());
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Add instructions" }));
    fireEvent.click(screen.getByRole("button", { name: "Executive brief" }));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(PRESETS[0]!.text);
    await waitFor(() =>
      expect(api.previewAiInstructions).toHaveBeenCalledWith(
        { text: PRESETS[0]!.text },
        "workspace",
      ),
    );
    expect(await screen.findByText("Preview — not saved yet")).toBeInTheDocument();
    expect(api.putAiInstructions).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sales discovery" })).toBeDisabled();
  });

  it("ships the four presets byte-identical to the fixtures", () => {
    expect(PRESETS.map((p) => p.id)).toEqual([
      "executive_brief",
      "client_ready_de",
      "engineering_standup",
      "sales_discovery",
    ]);
    for (const preset of PRESETS) {
      const file = readFileSync(resolve(FIXTURES, `${preset.id}.txt`), "utf-8");
      expect(file).toBe(`${preset.text}\n`);
    }
  });
});

describe("instructions per meeting type", () => {
  it("loads the chosen tab and shows the combined readout with its parent", async () => {
    api.getAiInstructions.mockImplementation(async (scope?: string) =>
      scope === "client"
        ? instructions({
            scope: "client",
            version: 1,
            text: "Keep topic sections.",
            understood: ["Shorter than standard — about 60 % of the usual length."],
            not_applied: [],
            extends: { scope: "workspace", version: 2 },
          })
        : instructions({
            scopes: [
              { scope: "workspace", version: 2, stale: false },
              { scope: "client", version: 1, stale: true },
            ],
          }),
    );
    renderCard();
    const tab = await screen.findByRole("tab", { name: /Client calls/ });
    expect(tab).toHaveTextContent("Updating…");
    expect(tab.querySelector(".scope-dot")).not.toBeNull();
    fireEvent.click(tab);
    expect(
      await screen.findByText(/Extends the workspace instructions \(v2\)/),
    ).toBeInTheDocument();
    expect(api.getAiInstructions).toHaveBeenCalledWith("client");
    expect(screen.getByText("Keep topic sections.")).toBeInTheDocument();
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
      prompt_version: "2026-10-18.6",
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
      instructions({
        scope: "note",
        version: 0,
        text: "",
        understood: [],
        not_applied: [],
        ...existing,
      }),
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

  it("saves, then rewrites", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Save and rewrite" }));
    await waitFor(() => expect(onRewritten).toHaveBeenCalled());
    expect(order).toEqual(["put", "regenerate"]);
    expect(api.putNoteInstructions).toHaveBeenCalledWith("n1", { text: "One paragraph." });
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
    fireEvent.click(screen.getByRole("button", { name: "Save and rewrite" }));
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

  it("names the meeting type's, the note's, or the fallback", async () => {
    expect(await status({ scope: "client", version: 1 })).toContain(
      "Written with client-call instructions v1",
    );
  });
  it("names this note's own", async () => {
    expect(await status({ scope: "note", version: 1 })).toContain(
      "Written with this note's instructions",
    );
  });
  it("says when a stale type text was skipped", async () => {
    expect(await status({ scope: "workspace", version: 3, fallback: "stale" })).toContain(
      "workspace instructions v3 (workspace instructions used — the meeting type's text is being updated)",
    );
  });
});
