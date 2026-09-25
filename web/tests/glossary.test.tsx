import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/http";
import { GlossarySection, NOT_VOCABULARY } from "../src/components/GlossarySection";
import {
  RememberTermPrompt,
  heardAsOf,
  isWorthRemembering,
  type PendingTerm,
} from "../src/components/RememberTermPrompt";
import { ToasterProvider } from "../src/components/Toaster";
import { MeetingPage } from "../src/pages/MeetingPage";

const glossary = vi.hoisted(() => ({
  listGlossary: vi.fn(),
  rememberTerm: vi.fn(),
  forgetTerm: vi.fn(),
  glossaryHint: vi.fn(),
}));
vi.mock("../src/api/glossary", () => glossary);

const asr = vi.hoisted(() => ({ submitJob: vi.fn(), listJobs: vi.fn() }));
vi.mock("../src/api/asr", async (orig) => ({
  ...(await orig<typeof import("../src/api/asr")>()),
  ...asr,
}));
vi.mock("../src/api/notes", async (orig) => ({
  ...(await orig<typeof import("../src/api/notes")>()),
  notesBySourceJob: vi.fn().mockResolvedValue([]),
}));

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  };
}

function term(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: "t-1",
    term: "John Mayer",
    kind: "person",
    heard_as: ["Jon Meyer"],
    created_at: "2026-09-20T00:00:00Z",
    can_delete: true,
    ...over,
  };
}

function renderSection() {
  return render(
    <MemoryRouter>
      <ToasterProvider>
        <GlossarySection />
      </ToasterProvider>
    </MemoryRouter>,
  );
}

function renderPrompt(pending: PendingTerm, onDone = vi.fn()) {
  render(
    <ToasterProvider>
      <RememberTermPrompt pending={pending} onDone={onDone} />
    </ToasterProvider>,
  );
  return onDone;
}

beforeEach(() => {
  vi.stubGlobal("localStorage", memoryStorage());
  glossary.listGlossary.mockReset().mockResolvedValue([]);
  glossary.rememberTerm.mockReset().mockResolvedValue(term());
  glossary.forgetTerm.mockReset().mockResolvedValue(undefined);
  glossary.glossaryHint.mockReset().mockResolvedValue({ hint: "", terms: 0 });
  asr.listJobs.mockReset().mockResolvedValue([]);
  asr.submitJob.mockReset().mockResolvedValue({ id: "job-9", status: "queued" });
});
afterEach(() => vi.unstubAllGlobals());

describe("the workspace vocabulary is visible and removable", () => {
  it("lists the terms with what they were heard as", async () => {
    glossary.listGlossary.mockResolvedValue([term()]);
    renderSection();
    expect(await screen.findByText("John Mayer")).toBeInTheDocument();
    expect(screen.getByText("heard as Jon Meyer")).toBeInTheDocument();
  });

  it("says what will happen when there is nothing yet", async () => {
    renderSection();
    expect(await screen.findByText(/we'll offer to remember it/i)).toBeInTheDocument();
  });

  it("adds a term", async () => {
    renderSection();
    await screen.findByText(/Nothing yet/i);
    fireEvent.change(screen.getByLabelText("Term"), { target: { value: "Contoso" } });
    fireEvent.click(screen.getByRole("button", { name: "Company" }));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(glossary.rememberTerm).toHaveBeenCalledWith({ term: "Contoso", kind: "company" }),
    );
  });

  it("offers Forget only on the terms this viewer may remove", async () => {
    glossary.listGlossary.mockResolvedValue([
      term(),
      term({ id: "t-2", term: "Contoso", heard_as: [], can_delete: false }),
    ]);
    renderSection();
    await screen.findByText("Contoso");
    expect(screen.getByRole("button", { name: "Forget John Mayer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Forget Contoso" })).toBeNull();
  });

  it("forgets a term", async () => {
    glossary.listGlossary.mockResolvedValue([term()]);
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Forget John Mayer" }));
    await waitFor(() => expect(glossary.forgetTerm).toHaveBeenCalledWith("t-1"));
    expect(screen.queryByText("John Mayer")).toBeNull();
  });
});

describe("nothing is remembered without being asked", () => {
  it("offers, and only writes on a yes", async () => {
    const onDone = vi.fn();
    render(
      <ToasterProvider>
        <RememberTermPrompt pending={{ term: "John Mayer", heardAs: "Jon Meyer" }} onDone={onDone} />
      </ToasterProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(glossary.rememberTerm).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalled();
  });

  it("sends the old spelling as what it was heard as", async () => {
    render(
      <ToasterProvider>
        <RememberTermPrompt pending={{ term: "John Mayer", heardAs: "Jon Meyer" }} onDone={vi.fn()} />
      </ToasterProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Remember" }));
    await waitFor(() =>
      expect(glossary.rememberTerm).toHaveBeenCalledWith({
        term: "John Mayer",
        kind: "person",
        heard_as: ["Jon Meyer"],
      }),
    );
  });

  it("only offers on a real correction", () => {
    expect(isWorthRemembering("Speaker 2", "John Mayer")).toBe(true);
    expect(isWorthRemembering("Jon Meyer", "John Mayer")).toBe(true);
    // Cleared back to a placeholder, or only case/spacing: teaches nothing.
    expect(isWorthRemembering("John Mayer", "Speaker 2")).toBe(false);
    expect(isWorthRemembering("john mayer", "John Mayer")).toBe(false);
    // The server collapses whitespace, so spacing alone is no change.
    expect(isWorthRemembering("John  Mayer ", "John Mayer")).toBe(false);
    expect(isWorthRemembering("Speaker 2", "J")).toBe(false);
    expect(isWorthRemembering("Speaker 2", "x".repeat(81))).toBe(false);
  });

  it("refuses the invisible characters that make one name render as another", () => {
    expect(isWorthRemembering("Speaker 2", "John‮Mayer")).toBe(false);
    expect(isWorthRemembering("Speaker 2", "Jo​hn")).toBe(false);
  });

  it("records a previous name, but never a placeholder", () => {
    expect(heardAsOf("Jon Meyer")).toBe("Jon Meyer");
    expect(heardAsOf("Speaker 2")).toBe("");
    expect(heardAsOf("")).toBe("");
  });
});

describe("the capture form knows the workspace's names", () => {
  it("pre-fills the vocabulary from the glossary", async () => {
    glossary.glossaryHint.mockResolvedValue({ hint: "John Mayer, Contoso", terms: 2 });
    render(
      <MemoryRouter initialEntries={["/meeting/new"]}>
        <ToasterProvider>
          <MeetingPage />
        </ToasterProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Options" }));
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/Names, product terms/)).toHaveValue(
        "John Mayer, Contoso",
      ),
    );
  });

  it("leaves an empty field when the workspace has no terms", async () => {
    render(
      <MemoryRouter initialEntries={["/meeting/new"]}>
        <ToasterProvider>
          <MeetingPage />
        </ToasterProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Options" }));
    await waitFor(() => expect(glossary.glossaryHint).toHaveBeenCalled());
    expect(screen.getByPlaceholderText(/Names, product terms/)).toHaveValue("");
  });
});

// ── Sprint I2: a role label is not a name ─────────────────────────────

describe("a role label never gets into the vocabulary (Sprint I2)", () => {
  it("is refused inline before anything is sent", async () => {
    renderSection();
    await screen.findByText(/Nothing yet/i);
    fireEvent.change(screen.getByLabelText("Term"), { target: { value: "Moderator II" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("alert")).toHaveTextContent(NOT_VOCABULARY);
    expect(glossary.rememberTerm).not.toHaveBeenCalled();
    // Typing again clears the message.
    fireEvent.change(screen.getByLabelText("Term"), { target: { value: "Moderator III" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the same sentence when the server is the one that refuses", async () => {
    glossary.rememberTerm.mockRejectedValue(
      new ApiError(422, { status: 422, code: "term_not_vocabulary", detail: "server wording" }),
    );
    renderSection();
    await screen.findByText(/Nothing yet/i);
    fireEvent.change(screen.getByLabelText("Term"), { target: { value: "Gregor Gysi" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(NOT_VOCABULARY);
    expect(screen.queryByText("server wording")).toBeNull();
  });

  it("flags stored labels the server no longer sends, dimmed and still removable", async () => {
    glossary.listGlossary.mockResolvedValue([
      term(),
      term({ id: "t-2", term: "Moderator II", heard_as: [], in_hint: false }),
      term({ id: "t-3", term: "moderatorin", heard_as: [], in_hint: false }),
    ]);
    renderSection();
    await screen.findByText("Moderator II");
    // (The toaster is a status region too; the banner is found by its class.)
    expect(document.querySelector(".glossary-not-sent")).toHaveTextContent(
      "2 entries are role labels, not names — they are no longer sent to the transcriber; remove them",
    );
    const row = screen.getByText("Moderator II").closest("li")!;
    expect(row).toHaveClass("not-sent");
    expect(row).toHaveTextContent("not sent");
    expect(screen.getByText("John Mayer").closest("li")).not.toHaveClass("not-sent");
    expect(screen.getAllByText("not sent")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Forget Moderator II" })).toBeInTheDocument();
  });

  it("speaks in the singular for one", async () => {
    glossary.listGlossary.mockResolvedValue([term({ term: "Narrator", in_hint: false })]);
    renderSection();
    await screen.findByText("Narrator");
    expect(document.querySelector(".glossary-not-sent")).toHaveTextContent(
      "1 entry is a role label, not a name — it is no longer sent to the transcriber; remove it",
    );
  });

  it("shows no banner when everything is sent", async () => {
    glossary.listGlossary.mockResolvedValue([term({ in_hint: true }), term({ id: "t-2", term: "Contoso" })]);
    renderSection();
    await screen.findByText("Contoso");
    expect(document.querySelector(".glossary-not-sent")).toBeNull();
  });
});

describe("the prompt is shown as it will be sent (Sprint I2)", () => {
  it("prints the exact hint with its term count", async () => {
    glossary.listGlossary.mockResolvedValue([term(), term({ id: "t-2", term: "Contoso" })]);
    glossary.glossaryHint.mockResolvedValue({ hint: "John Mayer, Contoso", terms: 2 });
    renderSection();
    const block = await screen.findByLabelText("What the transcriber is told");
    expect(block).toHaveTextContent("What the transcriber is told for the next recording");
    expect(block).toHaveTextContent("2 terms");
    expect(block.querySelector(".glossary-hint-text")).toHaveTextContent("John Mayer, Contoso");
  });

  it("refetches the hint after a term is added and after one is forgotten", async () => {
    glossary.listGlossary.mockResolvedValue([term()]);
    glossary.glossaryHint.mockResolvedValue({ hint: "John Mayer", terms: 1 });
    renderSection();
    await screen.findByRole("button", { name: "Forget John Mayer" });
    expect(glossary.glossaryHint).toHaveBeenCalledTimes(1);

    glossary.glossaryHint.mockResolvedValue({ hint: "John Mayer, Contoso", terms: 2 });
    fireEvent.change(screen.getByLabelText("Term"), { target: { value: "Contoso" } });
    fireEvent.click(screen.getByRole("button", { name: "Company" }));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(glossary.glossaryHint).toHaveBeenCalledTimes(2));
    await screen.findByText("2 terms");

    glossary.glossaryHint.mockResolvedValue({ hint: "", terms: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Forget John Mayer" }));
    await waitFor(() => expect(glossary.glossaryHint).toHaveBeenCalledTimes(3));
    await screen.findByText("0 terms");
    expect(screen.getByText(/the transcriber gets no names/i)).toBeInTheDocument();
  });

  it("says where a term came from, and when", async () => {
    glossary.listGlossary.mockResolvedValue([
      term({ source_note_id: "note-77" }),
      term({ id: "t-2", term: "Contoso", source_note_id: null }),
    ]);
    renderSection();
    await screen.findByText("Contoso");
    const link = screen.getByRole("link", { name: "from a note" });
    expect(link).toHaveAttribute("href", "/notes/note-77");
    expect(screen.getAllByRole("link", { name: "from a note" })).toHaveLength(1);
    expect(screen.getAllByText(/^added /)).toHaveLength(2);
  });
});

describe("the offer to remember (Sprint I2 wording)", () => {
  it("says what remembering means", () => {
    renderPrompt({ term: "John Mayer", heardAs: "Jon Meyer" });
    expect(document.querySelector(".remember-term")).toHaveTextContent(
      'Send "John Mayer" to the transcriber for every recording in this workspace?',
    );
    expect(screen.getByRole("button", { name: "Not now" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remember" })).toBeInTheDocument();
  });

  it.each(["Moderator II", "moderatorin", "speaker background", "Ведучий"])(
    "is not made at all for the role label %j",
    (label) => {
      renderPrompt({ term: label, heardAs: "Speaker 2" });
      expect(document.querySelector(".remember-term")).toBeNull();
      expect(screen.queryByRole("button", { name: "Remember" })).toBeNull();
    },
  );

  it("tells the server which note the rename happened in", async () => {
    renderPrompt({ term: "John Mayer", heardAs: "Jon Meyer", noteId: "note-77" });
    fireEvent.click(screen.getByRole("button", { name: "Remember" }));
    await waitFor(() =>
      expect(glossary.rememberTerm).toHaveBeenCalledWith({
        term: "John Mayer",
        kind: "person",
        heard_as: ["Jon Meyer"],
        note_id: "note-77",
      }),
    );
  });
});
