import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../src/auth/AuthContext";
import { setSessionListener } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import { LoginPage } from "../src/pages/LoginPage";
import { PasswordLoginPage } from "../src/pages/auth/PasswordLoginPage";
import { WelcomePage, suggestName } from "../src/pages/auth/WelcomePage";

/**
 * WEB-1: the signup path, at the level Playwright cannot reach cheaply.
 *
 * The browser test (`e2e/first-use.spec.ts`) proves the whole journey
 * against a real auth-service; these prove the branches that need a server
 * answering something specific — a `use_password` refusal, a `PATCH` body
 * carrying a time zone nobody typed — which is fiddly to arrange for real
 * and trivial to arrange here.
 */

const IDENTITY = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "alex.kim@example.test",
  display_name: "",
  mfa_enabled: false,
  has_password: false,
  status: "active",
};

const AUTH_RESULT = {
  status: "authenticated",
  access_token: "at",
  expires_in: 900,
  tenant_id: "22222222-2222-4222-8222-222222222222",
  roles: ["owner"],
  is_new_identity: true,
  identity: IDENTITY,
  memberships: [
    {
      tenant_id: "22222222-2222-4222-8222-222222222222",
      name: "Alex Kim",
      kind: "personal",
      role: "owner",
      status: "active",
    },
  ],
  default_tenant_id: null,
  challenge_id: null,
  methods: null,
  recovery_codes_left: null,
  recovery_codes_exhausted: null,
};

type Reply = { status?: number; body?: unknown };

/**
 * Route table keyed by `"METHOD /path"`, falling back to `"/path"`;
 * anything unlisted is a 404. The method matters here because `/auth/me`
 * is two different endpoints depending on the verb.
 */
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

/** Renders the signed-out routes and reports where the router ended up. */
function app(initial: string, state?: unknown) {
  function Where() {
    const location = useLocation();
    return (
      <span data-testid="where">
        {location.pathname}
        {(location.state as { focusNewMeeting?: boolean } | null)?.focusNewMeeting ? "#focus" : ""}
      </span>
    );
  }
  return render(
    <ToasterProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[{ pathname: initial, state }]}>
          <Where />
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/login/password" element={<PasswordLoginPage />} />
            <Route path="/welcome" element={<WelcomePage />} />
            <Route path="/" element={<div>home</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </ToasterProvider>,
  );
}

beforeEach(() => setSessionListener({}));
afterEach(() => vi.unstubAllGlobals());

describe("name suggestion", () => {
  it.each([
    ["alex.kim@example.com", "Alex Kim"],
    ["ALEX_KIM@example.com", "Alex Kim"],
    ["alex.kim+notes@example.com", "Alex Kim"],
    ["dana-oyelaran@example.com", "Dana Oyelaran"],
  ])("turns %s into %s", (email, expected) => {
    expect(suggestName(email)).toBe(expected);
  });

  it.each([
    // A role mailbox is not a person.
    "info@example.com",
    "sales@example.com",
    // An opaque handle Title-Cased is a worse guess than no guess.
    "k1n2m3@example.com",
    "jd@example.com",
    "user42@example.com",
  ])("declines to guess from %s", (email) => {
    expect(suggestName(email)).toBe("");
  });

  it("survives an address it never gets", () => {
    expect(suggestName(undefined)).toBe("");
  });
});

describe("/welcome", () => {
  it("prefills the name from the address and sends the time zone nobody typed", async () => {
    const calls = server({
      "/auth/refresh": { body: { access_token: "at", expires_in: 900 } },
      "/auth/me": { body: { claims: {}, db_user: null, identity: IDENTITY, memberships: [] } },
      "PATCH /auth/me": { body: IDENTITY },
    });

    app("/welcome");

    const box = await screen.findByLabelText<HTMLInputElement>(/your name/i);
    await waitFor(() => expect(box.value).toBe("Alex Kim"));

    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/#focus"));
    const patch = calls.find((c) => c.method === "PATCH" && c.path === "/auth/me")!;
    expect(patch.body).toMatchObject({ display_name: "Alex Kim" });
    // Whatever the machine says it is — the assertion is that it was sent
    // without a question, not that this box is in any particular zone.
    expect((patch.body as { timezone?: string }).timezone).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone,
    );
  });

  it("no password field appears anywhere on the way in", async () => {
    server({
      "/auth/refresh": { body: { access_token: "at", expires_in: 900 } },
      "/auth/me": { body: { claims: {}, db_user: null, identity: IDENTITY, memberships: [] } },
    });
    const { container } = app("/welcome");
    await screen.findByLabelText(/your name/i);
    expect(container.querySelector('input[type="password"]')).toBeNull();
  });
});

describe("the code step", () => {
  async function typeEmailAndCode(code: string) {
    await userEvent.type(screen.getByLabelText(/email/i), "alex.kim@example.test");
    await userEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    const boxes = await screen.findAllByRole("textbox");
    // The first box takes a paste of the whole code.
    await userEvent.click(boxes[0]!);
    await userEvent.paste(code);
  }

  it("hands a use_password account to the password form, address and all", async () => {
    server({
      "/auth/refresh": { status: 401 },
      "/auth/email/start": {
        status: 202,
        body: { challenge_id: "c1", expires_in: 600, resend_after: 60 },
      },
      "/auth/email/verify": {
        status: 409,
        body: { code: "use_password", detail: "this account uses a password" },
      },
    });
    app("/login");
    await screen.findByRole("button", { name: /email me a code/i });
    await typeEmailAndCode("482913");

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/login/password"));
    // The address survives the switch: being redirected is not a reason to
    // make somebody type it again.
    expect(await screen.findByLabelText<HTMLInputElement>(/^email$/i)).toHaveValue(
      "alex.kim@example.test",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/signs in with a password/i);
  });

  it("sends an MFA account to the second factor rather than to a password", async () => {
    server({
      "/auth/refresh": { status: 401 },
      "/auth/email/start": {
        status: 202,
        body: { challenge_id: "c1", expires_in: 600, resend_after: 60 },
      },
      "/auth/email/verify": {
        body: {
          ...AUTH_RESULT,
          status: "mfa_required",
          access_token: "",
          challenge_id: "m1",
          methods: ["totp"],
          identity: null,
          memberships: [],
        },
      },
    });
    app("/login");
    await screen.findByRole("button", { name: /email me a code/i });
    await typeEmailAndCode("482913");

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/login/mfa"));
  });

  it("takes a new identity to /welcome, not to the notes list", async () => {
    server({
      "/auth/refresh": { status: 401 },
      "/auth/email/start": {
        status: 202,
        body: { challenge_id: "c1", expires_in: 600, resend_after: 60 },
      },
      "/auth/email/verify": { body: AUTH_RESULT },
      "/auth/me": { body: { claims: {}, db_user: null, identity: IDENTITY, memberships: [] } },
    });
    app("/login");
    await screen.findByRole("button", { name: /email me a code/i });
    await typeEmailAndCode("482913");

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/welcome"));
  });
});
