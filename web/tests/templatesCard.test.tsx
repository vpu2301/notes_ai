import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RegenerateSheet } from "../src/components/RegenerateSheet";
import { TemplatesCard } from "../src/components/TemplatesCard";
import { ToasterProvider } from "../src/components/Toaster";

const api = vi.hoisted(() => ({
  getTemplates: vi.fn(),
  putTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
}));
vi.mock("../src/api/aiTemplates", () => api);
const gen = vi.hoisted(() => ({ regenerate: vi.fn() }));
vi.mock("../src/api/generation", () => gen);

const NAMES = ["meeting", "client_call", "interview", "broadcast", "public_meeting", "memo", "auto"];

function templates(language = "en", canEdit = true, customised: string[] = []) {
  return NAMES.map((name) => ({
    name,
    language,
    source: customised.includes(name) ? "workspace" : "builtin",
    markdown: `## ${name} (${language})\n- a line`,
    can_edit: canEdit,
    updated_at: customised.includes(name) ? "2026-10-21T10:00:00Z" : null,
    updated_by: null,
  }));
}

function renderCard() {
  return render(
    <MemoryRouter>
      <ToasterProvider>
        <TemplatesCard />
      </ToasterProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const fn of [...Object.values(api), ...Object.values(gen)]) fn.mockReset();
});

describe("templates card (P2)", () => {
  it("lists the seven templates of the chosen language with their source", async () => {
    api.getTemplates.mockImplementation(async (language: string) =>
      templates(language, true, ["meeting"]),
    );
    renderCard();
    expect(await screen.findByRole("button", { name: "Meeting" })).toBeInTheDocument();
    expect(api.getTemplates).toHaveBeenCalledWith("en");
    for (const label of ["Client call", "Interview", "Broadcast", "Public meeting", "Memo", "Automatic"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Customised")).toHaveLength(1);
    expect(screen.getAllByText("Built-in")).toHaveLength(6);
    fireEvent.click(screen.getByRole("tab", { name: "Deutsch" }));
    await waitFor(() => expect(api.getTemplates).toHaveBeenCalledWith("de"));
  });

  it("edits a built-in text and saves it as the workspace's own", async () => {
    api.getTemplates.mockResolvedValue(templates());
    api.putTemplate.mockResolvedValue({
      ...templates()[0]!,
      source: "workspace",
      markdown: "## Decisions\n- one per line",
    });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Meeting" }));
    expect(screen.getByText(/## meeting \(en\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Meeting template" });
    expect(box).toHaveAttribute("maxlength", "4000");
    fireEvent.change(box, { target: { value: "## Decisions\n- one per line" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.putTemplate).toHaveBeenCalledWith("meeting", {
        language: "en",
        markdown: "## Decisions\n- one per line",
      }),
    );
    expect(await screen.findByText(/Meeting template saved/)).toBeInTheDocument();
    expect(screen.getByText("Customised")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset to built-in" })).toBeInTheDocument();
  });

  it("resets a customised template after a confirmation", async () => {
    api.getTemplates.mockResolvedValueOnce(templates("en", true, ["memo"]));
    api.getTemplates.mockResolvedValueOnce(templates());
    api.deleteTemplate.mockResolvedValue(undefined);
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Memo" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset to built-in" }));
    expect(api.deleteTemplate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(api.deleteTemplate).toHaveBeenCalledWith("memo", "en"));
    expect(await screen.findByText(/Memo template reset/)).toBeInTheDocument();
    await waitFor(() => expect(api.getTemplates).toHaveBeenCalledTimes(2));
  });

  it("gives a member the texts and no Edit", async () => {
    api.getTemplates.mockResolvedValue(templates("en", false, ["meeting"]));
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Meeting" }));
    expect(screen.getByText(/## meeting \(en\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit|Reset to built-in/ })).toBeNull();
  });
});

describe("regenerate as… (P2)", () => {
  it("sends the chosen template with the regenerate call", async () => {
    gen.regenerate.mockResolvedValue({ id: "g", status: "queued" });
    const onRegenerated = vi.fn();
    render(
      <ToasterProvider>
        <RegenerateSheet noteId="n1" current={null} onClose={vi.fn()} onRegenerated={onRegenerated} />
      </ToasterProvider>,
    );
    expect(screen.getByRole("radio", { name: "Automatic" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("radio", { name: "Interview" }));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(gen.regenerate).toHaveBeenCalledWith("n1", "interview"));
    expect(onRegenerated).toHaveBeenCalled();
  });
});
