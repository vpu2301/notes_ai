import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSessionListener } from "../src/api/http";
import { AuthProvider } from "../src/auth/AuthContext";
import { ToasterProvider } from "../src/components/Toaster";
import { PasswordLoginPage } from "../src/pages/auth/PasswordLoginPage";
import { SignupPage } from "../src/pages/auth/SignupPage";

/**
 * BE-0's web half: `/signup`.
 *
 * The branches worth pinning here are the ones a browser test cannot see
 * cheaply — what the screen *says* when the server deliberately tells it
 * nothing (the uniform 202), and that verification is followed by a
 * sign-in rather than by a second password prompt.
 */

const IDENTITY = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "alex.kim@example.test",
  display_name: "Alex Kim",
  mfa_enabled: false,
  has_password: true,
  status: "active",
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

function app(initial: string, state?: unknown) {
  function Where() {
    const location = useLocation();
    return <span data-testid="where">{location.pathname}</span>;
  }
  return render(
    <ToasterProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[{ pathname: initial, state }]}>
          <Where />
          <Routes>
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/login/password" element={<PasswordLoginPage />} />
            <Route path="/" element={<div>home</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </ToasterProvider>,
  );
}

/** The three boxes of step 1, filled. */
async function fillForm(password = "correct horse battery staple") {
  await userEvent.type(await screen.findByLabelText(/your name/i), "Alex Kim");
  await userEvent.type(screen.getByLabelText(/^email$/i), "alex.kim@example.test");
  await userEvent.type(screen.getByLabelText(/^password$/i), password);
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));
}

async function pasteCode(code: string) {
  const boxes = await screen.findAllByRole("textbox");
  await userEvent.click(boxes[0]!);
  await userEvent.paste(code);
}

const ANONYMOUS = { "/auth/refresh": { status: 401 } };
const ACCEPTED = { status: 202, body: { status: "verification_sent", resend_after: 60 } };

beforeEach(() => setSessionListener({}));
afterEach(() => vi.unstubAllGlobals());

describe("/signup", () => {
  it("creates the account and signs in with the password already typed", async () => {
    const calls = server({
      ...ANONYMOUS,
      "POST /auth/signup": ACCEPTED,
      "POST /auth/signup/verify": { body: { verified: true } },
      "POST /auth/login": { body: { access_token: "at", expires_in: 900 } },
      "/auth/me": { body: { claims: { tid: "t1" }, db_user: null, identity: IDENTITY, memberships: [] } },
    });

    app("/signup");
    await fillForm();
    await pasteCode("482913");

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/));

    const created = calls.find((c) => c.path === "/auth/signup")!;
    expect(created.body).toEqual({
      email: "alex.kim@example.test",
      password: "correct horse battery staple",
      display_name: "Alex Kim",
    });
    // Confirming an address is not a reason to ask for the password again.
    const login = calls.find((c) => c.path === "/auth/login")!;
    expect(login.body).toMatchObject({ email: "alex.kim@example.test" });
    // The name was asked for on step 1, so `/welcome` has nothing to ask —
    // but the time zone it would have sent is still sent.
    const patch = calls.find((c) => c.method === "PATCH" && c.path === "/auth/me");
    expect(patch?.body).toMatchObject({
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
  });

  it("never claims the address is new, because the 202 does not say", async () => {
    server({ ...ANONYMOUS, "POST /auth/signup": ACCEPTED });

    app("/signup");
    await fillForm();

    const card = await screen.findByText(/check your email/i);
    const text = card.closest("form, div")!.parentElement!.textContent ?? "";
    // The one honest shape: conditional, and with a way out for somebody
    // who is waiting for a code that is never coming.
    expect(text).toMatch(/if .*alex\.kim@example\.test.* is new here/i);
    expect(screen.getByRole("link", { name: /sign in instead/i })).toBeInTheDocument();
  });

  it("lists why a password was refused instead of just reddening the field", async () => {
    server({
      ...ANONYMOUS,
      "POST /auth/signup": {
        status: 400,
        body: {
          code: "password_policy",
          detail: "that password is too easy to guess",
          min_length: 12,
          reasons: ["too_short", "common"],
        },
      },
    });

    app("/signup");
    await fillForm("password");

    expect(await screen.findByRole("alert")).toHaveTextContent(/stronger password/i);
    // Scoped to the list: the standing hint under the field says "at least
    // 12 characters" too, and matching that would pass with no reasons.
    const reasons = within(screen.getByRole("list"));
    expect(reasons.getByText(/at least 12 characters/i)).toBeInTheDocument();
    expect(reasons.getByText(/every attacker's list/i)).toBeInTheDocument();
    // And it stayed on the form — there is nothing to confirm.
    expect(screen.getByLabelText(/your name/i)).toBeInTheDocument();
  });

  it("counts down the wrong-code attempts the server is counting", async () => {
    server({
      ...ANONYMOUS,
      "POST /auth/signup": ACCEPTED,
      "POST /auth/signup/verify": {
        status: 400,
        body: { code: "code_invalid", detail: "wrong code", attempts_left: 3 },
      },
    });

    app("/signup");
    await fillForm();
    await pasteCode("000000");

    expect(await screen.findByRole("alert")).toHaveTextContent(/not right\. 3 tries left/i);
  });

  it("keeps the code when the server asks to be tried again", async () => {
    server({
      ...ANONYMOUS,
      "POST /auth/signup": ACCEPTED,
      "POST /auth/signup/verify": {
        status: 409,
        body: { code: "verify_retry", detail: "keycloak unavailable" },
      },
    });

    app("/signup");
    await fillForm();
    await pasteCode("482913");

    // `verify_retry` does not consume the challenge, so the copy must not
    // send somebody off to ask for a code they already have.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/code still works/i);
    expect(alert).not.toHaveTextContent(/new code|ask for/i);
  });

  it("says so plainly where signup is not served", async () => {
    server(ANONYMOUS); // every /auth/signup* answers 404

    app("/signup");
    await fillForm();

    expect(await screen.findByRole("alert")).toHaveTextContent(/not available here/i);
  });

  it("puts an unfinished signup back on the password form once confirmed", async () => {
    server({
      ...ANONYMOUS,
      "POST /auth/signup/verify": { body: { verified: true } },
    });

    // How `/login/password` sends somebody here: address only, no password.
    app("/signup", { email: "alex.kim@example.test", verifyOnly: true });
    await pasteCode("482913");

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/login/password"));
    expect(await screen.findByText(/email is confirmed/i)).toBeInTheDocument();
    expect(screen.getByLabelText<HTMLInputElement>(/^email$/i)).toHaveValue(
      "alex.kim@example.test",
    );
  });

  it("carries no password into the router's history state", async () => {
    server({ ...ANONYMOUS, "POST /auth/signup": ACCEPTED });
    app("/signup", { email: "alex.kim@example.test", verifyOnly: true });
    await screen.findAllByRole("textbox");
    // The screen reached from `/login/password` asks for a code and nothing
    // else — a password would have to come through history state to be here.
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });
});

describe("/login/password meets an unconfirmed account", () => {
  it("offers the code rather than telling them the password was wrong", async () => {
    const calls = server({
      ...ANONYMOUS,
      "POST /auth/login": {
        status: 403,
        body: { code: "email_not_verified", detail: "email not verified" },
      },
      "POST /auth/signup/resend": ACCEPTED,
    });

    app("/login/password");
    await userEvent.type(await screen.findByLabelText(/^email$/i), "alex.kim@example.test");
    await userEvent.type(screen.getByLabelText(/^password$/i), "correct horse battery staple");
    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/confirm your email/i);

    await userEvent.click(screen.getByRole("button", { name: /email me the code again/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /code sent/i })).toBeDisabled(),
    );
    expect(calls.find((c) => c.path === "/auth/signup/resend")!.body).toEqual({
      email: "alex.kim@example.test",
    });

    // And the way to spend it is one click away.
    expect(screen.getByRole("link", { name: /i have the code/i })).toBeInTheDocument();
  });
});
