import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSessionListener } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import { NotesPage } from "../src/pages/NotesPage";
import { SpacesProvider } from "../src/spaces/SpacesContext";

/**
 * WEB-1b §2: "NotesPage with zero notes shows one line and the recorder
 * call-to-action, not an empty list; Coming up hides its calendar prompt
 * until the first note exists."
 *
 * The second half is the one worth a test. It is easy to write, easy to
 * regress (any future edit that mounts `<ComingUp />` unconditionally puts
 * it back), and it is the difference between a first screen that says
 * "press record" and one whose loudest button asks for a Google consent.
 */

const EMPTY_SEARCH = { hits: [], next_cursor: null };
const ONE_NOTE = {
  hits: [
    {
      note_id: "33333333-3333-4333-8333-333333333333",
      title: "Kickoff",
      snippet: "",
      status: "final",
      updated_at: new Date().toISOString(),
    },
  ],
  next_cursor: null,
};

/** A calendar backend that can be connected but is not — the prompt case. */
const NO_CONNECTIONS = { connections: [], available: true, link_available: true };

function server(notes: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const path = new URL(String(url)).pathname;
      const body =
        path === "/v1/notes/search"
          ? notes
          : path === "/v1/spaces"
            ? { spaces: [] }
            : path === "/v1/calendar/connections"
              ? NO_CONNECTIONS
              : path === "/v1/calendar/events"
                ? { events: [], problems: [] }
                : path === "/asr/jobs"
                  ? []
                  : null;
      if (body === null) return new Response("{}", { status: 404 });
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function home() {
  return render(
    <ToasterProvider>
      <MemoryRouter initialEntries={["/"]}>
        <SpacesProvider>
          <Routes>
            <Route path="/" element={<NotesPage />} />
          </Routes>
        </SpacesProvider>
      </MemoryRouter>
    </ToasterProvider>,
  );
}

beforeEach(() => setSessionListener({}));
afterEach(() => vi.unstubAllGlobals());

describe("the empty workspace", () => {
  it("offers the recorder and no calendar consent", async () => {
    server(EMPTY_SEARCH);
    home();

    await screen.findByRole("region", { name: /get started/i });
    // The call to action, not a list with nothing in it.
    expect(screen.queryByRole("region", { name: /coming up/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /connect google calendar/i })).toBeNull();
    // The recorder is reachable from the panel itself, not only the header.
    const region = screen.getByRole("region", { name: /get started/i });
    expect(region.querySelector("button.accent")).not.toBeNull();
  });

  it("says it once — the panel is a sentence, not a tour", async () => {
    server(EMPTY_SEARCH);
    home();

    const region = await screen.findByRole("region", { name: /get started/i });
    expect(region.querySelectorAll("p").length).toBeLessThanOrEqual(2);
  });

  it("brings the calendar prompt back as soon as there is a note", async () => {
    server(ONE_NOTE);
    home();

    await screen.findByText("Kickoff");
    await waitFor(() =>
      expect(screen.getByRole("region", { name: /coming up/i })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("region", { name: /get started/i })).toBeNull();
  });

  it("shows no calendar prompt while the note count is still unknown", async () => {
    // A search that never resolves: the page is loading, and "we don't
    // know yet" must not render as "there is nothing, so ask about Google".
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        const path = new URL(String(url)).pathname;
        if (path === "/v1/notes/search") return new Promise<Response>(() => {});
        const body =
          path === "/asr/jobs"
            ? []
            : path === "/v1/spaces"
              ? { spaces: [] }
              : path === "/v1/calendar/connections"
                ? NO_CONNECTIONS
                : { events: [], problems: [] };
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    home();

    await screen.findByLabelText(/loading notes/i);
    expect(screen.queryByRole("button", { name: /connect google calendar/i })).toBeNull();
  });
});
