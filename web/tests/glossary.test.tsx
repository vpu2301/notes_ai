import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GlossarySection } from "../src/components/GlossarySection";
import {
  RememberTermPrompt,
  heardAsOf,
  isWorthRemembering,
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
    <ToasterProvider>
      <GlossarySection />
    </ToasterProvider>,
  );
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
