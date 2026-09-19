import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSessionListener } from "../src/api/http";
import { SharedItems } from "../src/components/SharedItems";
import type { SharedItem } from "../src/api/types";

const TOKEN = "t".repeat(43);

const ITEMS: SharedItem[] = [
  { item_key: "k1", text: "Send proposal", owner_label: "Anna", due_date: "2026-09-18", due_text: "18 Sep", status: "open", my_response: null, my_comment: null },
  { item_key: "k2", text: "Share brand assets", owner_label: "Tom", due_date: null, due_text: null, status: "open", my_response: null, my_comment: null },
];

function server(status = 200) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      calls.push({
        method: (init?.method ?? "GET").toUpperCase(),
        path: new URL(String(url)).pathname,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      return new Response(JSON.stringify({ ok: true }), { status, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

beforeEach(() => setSessionListener({}));
afterEach(() => vi.unstubAllGlobals());

describe("shared page — who does what", () => {
  it("confirm calls the server and flips the row", async () => {
    const calls = server();
    render(<SharedItems token={TOKEN} items={ITEMS} canRespond onError={() => {}} />);
    await userEvent.click(screen.getAllByRole("button", { name: /confirm/i })[0]!);
    await waitFor(() =>
      expect(calls).toEqual([
        { method: "PUT", path: `/v1/shared/${TOKEN}/items/k1/response`, body: { kind: "confirm" } },
      ]),
    );
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText(/You responded to 1 of 2 items/)).toBeInTheDocument();
  });

  it("a dispute needs a comment of at most 280 characters", async () => {
    const calls = server();
    render(<SharedItems token={TOKEN} items={ITEMS} canRespond onError={() => {}} />);
    await userEvent.click(screen.getAllByRole("button", { name: /dispute/i })[0]!);
    const box = screen.getByLabelText(/what's different/i);
    await userEvent.type(box, "x".repeat(281));
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();
    await userEvent.clear(box);
    await userEvent.type(box, "It was Friday");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));
    await waitFor(() => expect(calls[0]?.body).toEqual({ kind: "dispute", comment: "It was Friday" }));
    expect(screen.getByText("You said: It was Friday")).toBeInTheDocument();
  });

  it("rolls back when the server refuses", async () => {
    server(429);
    const errors: string[] = [];
    render(<SharedItems token={TOKEN} items={ITEMS} canRespond onError={(m) => errors.push(m)} />);
    await userEvent.click(screen.getAllByRole("button", { name: /confirm/i })[0]!);
    await waitFor(() => expect(errors[0]).toMatch(/too many actions/i));
    expect(screen.queryByText("Confirmed")).not.toBeInTheDocument();
  });

  it("a public link shows no buttons", () => {
    server();
    render(<SharedItems token={TOKEN} items={ITEMS} canRespond={false} onError={() => {}} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("Send proposal")).toBeInTheDocument();
  });
});
