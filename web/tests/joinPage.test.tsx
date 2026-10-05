import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { setSessionListener } from "../src/api/http";
import { AuthProvider } from "../src/auth/AuthContext";
import { JoinPage, REF_STORAGE_KEY } from "../src/pages/JoinPage";

function stub(signupEnabled = false) {
  const calls: { path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (path === "/auth/signup/config") {
        return new Response(
          JSON.stringify({ enabled: signupEnabled, min_password_length: 12, disposable_domains_blocked: true }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (path === "/auth/password/policy") {
        return new Response(JSON.stringify({ min_length: 12 }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (path === "/auth/signup") {
        return new Response(JSON.stringify({ status: "verification_sent", resend_after: 60 }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ status: "accepted" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

function page(search = "?ref=abcdefghijkl") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[`/join${search}`]}>
        <Routes>
          <Route path="/join" element={<JoinPage />} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

beforeEach(() => {
  setSessionListener({});
  window.sessionStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("/join — the fake door", () => {
  it("submits the address with the ref and remembers the ref for /signup", async () => {
    const calls = stub();
    page();
    await userEvent.type(await screen.findByLabelText(/e-mail/i), "tom@client.com");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /open my workspace/i }));
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/auth/leads")).toEqual([
        { path: "/auth/leads", body: { email: "tom@client.com", ref: "abcdefghijkl", consent: true } },
      ]),
    );
    expect(await screen.findByText(/you're on the list/i)).toBeInTheDocument();
    expect(window.sessionStorage.getItem(REF_STORAGE_KEY)).toBe("abcdefghijkl");
  });

  it("refuses to submit without consent", async () => {
    const calls = stub();
    page("");
    await userEvent.type(await screen.findByLabelText(/e-mail/i), "tom@client.com");
    await userEvent.click(screen.getByRole("button", { name: /open my workspace/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/agree/i);
    expect(calls.filter((c) => c.path === "/auth/leads")).toEqual([]);
  });
});

describe("/join — with self-serve signup on (Sprint 21)", () => {
  it("shows the signup form and posts the referral code with the account", async () => {
    const calls = stub(true);
    page();
    await userEvent.type(await screen.findByLabelText(/your name/i), "Tom");
    await userEvent.type(screen.getByLabelText(/^email$/i), "tom@client.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "correct-horse-battery-staple-9");
    await userEvent.click(screen.getByRole("button", { name: /create/i }));
    await waitFor(() => expect(calls.some((c) => c.path === "/auth/signup")).toBe(true));
    const body = calls.find((c) => c.path === "/auth/signup")?.body as Record<string, unknown>;
    expect(body).toMatchObject({ email: "tom@client.com", display_name: "Tom", ref: "abcdefghijkl" });
    expect(calls.some((c) => c.path === "/auth/leads")).toBe(false);
  });

  it("falls back to the lead form when signup is off", async () => {
    stub(false);
    page();
    expect(await screen.findByRole("button", { name: /open my workspace/i })).toBeInTheDocument();
  });
});
