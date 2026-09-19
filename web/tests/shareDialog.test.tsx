import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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
  links: [],
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

describe("share sheet — client links (Sprint 19)", () => {
  const LINK = {
    id: "l1",
    kind: "recipient",
    label: "Tom @ Client",
    recipient_email: "tom@client.com",
    token: "t".repeat(43),
    path: `/s/${"t".repeat(43)}`,
    ref_code: "abcdefghijkl",
    created_at: "2026-09-16T12:00:00Z",
    expires_at: "2026-12-15T12:00:00Z",
    view_count: 0,
    first_viewed_at: null,
    last_viewed_at: null,
    cta_clicked_at: null,
  };

  it("creates a per-recipient link and shows it with Copy", async () => {
    const calls = server({
      ...LOADED,
      [`POST /v1/notes/${NOTE}/links`]: { status: 201, body: LINK },
    });
    sheet();
    await userEvent.click(await screen.findByRole("button", { name: /create a link without sending/i }));
    const label = await screen.findByLabelText(/recipient label/i);
    await userEvent.type(label, "Tom @ Client");
    await userEvent.type(screen.getByLabelText(/recipient e-mail/i), "tom@client.com");
    await userEvent.click(screen.getByRole("button", { name: /create link only/i }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/links"))?.body).toMatchObject({
        label: "Tom @ Client",
        recipient_email: "tom@client.com",
        expires_in_days: 90,
        send: false,
      }),
    );
    expect((await screen.findByLabelText(/client link/i)).getAttribute("value")).toContain(LINK.path);
  });

  it("creates a link for a draft without any acknowledgement (ADR-0051)", async () => {
    server({ ...LOADED, [`POST /v1/notes/${NOTE}/links`]: { status: 201, body: LINK } });
    render(
      <ToasterProvider>
        <ShareDialog noteId={NOTE} noteTitle="Acme kickoff" onClose={() => {}} />
      </ToasterProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /create a link without sending/i }));
    await userEvent.type(await screen.findByLabelText(/recipient label/i), "Tom");
    expect(screen.queryByText(/this note is a draft/i)).toBeNull();
    const create = screen.getByRole("button", { name: /create link/i });
    expect(create).toBeEnabled();
    await userEvent.click(create);
    expect((await screen.findByLabelText(/client link/i)).getAttribute("value")).toContain(LINK.path);
  });

  it("lists existing client links with their opened state", async () => {
    server({
      [`/v1/notes/${NOTE}/sharing`]: {
        body: { ...SHARING, links: [LINK, { ...LINK, id: "l2", label: "Ana", first_viewed_at: "2026-09-17T09:00:00Z" }] },
      },
    });
    sheet();
    const list = await screen.findByLabelText(/people with access/i);
    expect(list).toHaveTextContent("Tom @ Client");
    expect(list).toHaveTextContent("Not opened");
    expect(list).toHaveTextContent(/Opened (17 Sep|Sep 17)/);
  });
});

describe("share sheet — send from the product (Sprint 22)", () => {
  const SENT = { ...LINK_BASE(), delivery_status: "sent", sent_at: "2026-09-17T12:31:00Z", send_count: 1 };

  it("Send mails an outsider their own link, with the chosen expiry, and lists it as Sent", async () => {
    const calls = server({
      ...LOADED,
      [`POST /v1/notes/${NOTE}/share/email`]: {
        body: {
          sharing: { ...SHARING, links: [SENT] },
          results: [{ email: "tom@client.com", access: "link", status: "sent" }],
          public_link_created: false,
        },
      },
    });
    sheet();
    await userEvent.type(await screen.findByLabelText(/e-mail address/i), "tom@client.com");
    await userEvent.type(screen.getByLabelText(/^message$/i), "See you Friday");
    await userEvent.click(screen.getByRole("button", { name: /link expires after/i }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /30 days/i }));
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/share/email"))?.body).toMatchObject({
        recipients: ["tom@client.com"],
        message: "See you Friday",
        expires_in_days: 30,
      }),
    );
    const list = await screen.findByLabelText(/people with access/i);
    expect(list).toHaveTextContent("Tom @ Client");
    expect(list).toHaveTextContent(/Sent/);
  });

  it("an opted-out recipient has no send button, but copy still works", async () => {
    server({
      [`/v1/notes/${NOTE}/sharing`]: {
        body: { ...SHARING, links: [{ ...LINK_BASE(), delivery_status: "suppressed", send_count: 1 }] },
      },
    });
    sheet();
    const list = await screen.findByLabelText(/people with access/i);
    expect(list).toHaveTextContent("Opted out");
    expect(within(list).queryByRole("button", { name: /^(send|resend|retry)$/i })).not.toBeInTheDocument();
    expect(within(list).getByRole("button", { name: /^copy$/i })).toBeInTheDocument();
  });

  it("a failed send offers Retry and a sent one offers Resend", async () => {
    server({
      [`/v1/notes/${NOTE}/sharing`]: {
        body: {
          ...SHARING,
          links: [
            { ...LINK_BASE(), id: "f", delivery_status: "failed", send_count: 1, last_send_error: "EmailDeliveryError" },
            { ...LINK_BASE(), id: "s", label: "Ana", delivery_status: "sent", send_count: 1 },
          ],
        },
      },
    });
    sheet();
    await screen.findByLabelText(/people with access/i);
    expect(screen.getByRole("button", { name: /^retry$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^resend$/i })).toBeInTheDocument();
  });
});

function LINK_BASE() {
  return {
    id: "l1",
    kind: "recipient",
    label: "Tom @ Client",
    recipient_email: "tom@client.com",
    token: "t".repeat(43),
    path: `/s/${"t".repeat(43)}`,
    ref_code: "abcdefghijkl",
    created_at: "2026-09-16T12:00:00Z",
    expires_at: "2026-12-15T12:00:00Z",
    view_count: 0,
    first_viewed_at: null,
    last_viewed_at: null,
    cta_clicked_at: null,
    response_count: 0,
    delivery_status: "not_sent",
    sent_at: null,
    send_count: 0,
  };
}
