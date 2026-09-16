import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSessionListener } from "../src/api/http";
import { ShareDialog } from "../src/components/ShareDialog";
import { ToasterProvider } from "../src/components/Toaster";

/**
 * The share sheet's compose box.
 *
 * What is worth pinning here is that pressing Send actually calls the
 * server, with everyone the sender named. The behaviour it replaced —
 * `window.location.href = "mailto:…"` — could not be tested at all in a
 * browser, which is a good part of why nobody noticed it was handing the
 * job to whatever draft Mail.app had lying around.
 */

const NOTE = "note-1";

const SHARING = {
  note_id: NOTE,
  visibility: "private",
  can_manage: true,
  can_delete: true,
  shared_with: [],
  public_link: null,
};

type Reply = { status?: number; body?: unknown };

function server(routes: Record<string, Reply>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, path, body });
      const reply = routes[`${method} ${path}`] ?? routes[path];
      if (!reply) return new Response("{}", { status: 404 });
      return new Response(JSON.stringify(reply.body ?? {}), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

function sheet() {
  return render(
    <ToasterProvider>
      <ShareDialog noteId={NOTE} noteTitle="Acme kickoff" onClose={() => {}} />
    </ToasterProvider>,
  );
}

const LOADED = { [`/v1/notes/${NOTE}/sharing`]: { body: SHARING } };

function sendResult(results: { email: string; access: string; status: string }[]) {
  return { body: { sharing: SHARING, results, public_link_created: false } };
}

beforeEach(() => setSessionListener({}));
afterEach(() => vi.unstubAllGlobals());

describe("share sheet — send by e-mail", () => {
  it("sends everyone named to the server, with the message", async () => {
    const calls = server({
      ...LOADED,
      [`POST /v1/notes/${NOTE}/share/email`]: sendResult([
        { email: "a@example.com", access: "member", status: "sent" },
        { email: "b@example.com", access: "link", status: "sent" },
      ]),
    });

    sheet();
    const box = await screen.findByLabelText(/e-mail address/i);
    // Comma commits the first address; the second is still half-typed
    // when Send is pressed, which is exactly how people use these boxes.
    await userEvent.type(box, "a@example.com,b@example.com");
    await userEvent.type(screen.getByLabelText(/message/i), "Recap inside.");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => {
      const sent = calls.find((c) => c.path.endsWith("/share/email"));
      expect(sent?.body).toMatchObject({
        recipients: ["a@example.com", "b@example.com"],
        message: "Recap inside.",
      });
    });
    // Nothing was handed to a mail client.
    expect(await screen.findByText(/sent to 2 people/i)).toBeInTheDocument();
  });

  it("refuses to send something that is not an address", async () => {
    const calls = server(LOADED);

    sheet();
    await userEvent.type(await screen.findByLabelText(/e-mail address/i), "not an address");
    // A space is a chip separator, so what is left in the box is the
    // tail — either way nothing is sent and the sender is told why.
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    expect(await screen.findByText(/doesn’t look like an e-mail address/i)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/share/email"))).toBe(false);
  });

  it("keeps a refused address in the box so the typo can be fixed", async () => {
    server({
      ...LOADED,
      [`POST /v1/notes/${NOTE}/share/email`]: sendResult([
        { email: "good@example.com", access: "link", status: "sent" },
        { email: "typo@exmaple.com", access: "link", status: "rejected" },
      ]),
    });

    sheet();
    await userEvent.type(
      await screen.findByLabelText(/e-mail address/i),
      "good@example.com typo@exmaple.com",
    );
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    expect(await screen.findByText(/did not go out/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove typo@exmaple\.com/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove good@example\.com/i })).toBeNull();
  });
});
