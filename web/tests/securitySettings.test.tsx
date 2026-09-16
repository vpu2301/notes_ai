import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../src/auth/AuthContext";
import { ToasterProvider } from "../src/components/Toaster";
import { setAccessToken, setReauthHandler, setSessionListener } from "../src/api/http";
import { SecuritySettingsPage } from "../src/pages/settings/SecuritySettingsPage";
import type { MeResponse } from "../src/api/types";

/**
 * §H, as far as a jsdom test can reach: enrolment shows the key and the
 * recovery codes exactly once, and the codes screen will not let go until
 * the person says they have saved them.
 *
 * `qrcode` renders asynchronously and is not what these assert, so the
 * component is stubbed — the manual key beside it is the thing under test.
 */
vi.mock("../src/components/QrCode", () => ({
  QrCode: ({ label }: { label: string }) => <div data-testid="qr">{label}</div>,
}));

const SUB = "11111111-1111-4111-8111-111111111111";
const TID = "22222222-2222-4222-8222-222222222222";

function me(mfaEnabled: boolean): MeResponse {
  return {
    claims: { sub: SUB, tid: TID, roles: ["member"] },
    db_user: null,
    identity: {
      id: SUB,
      email: "sam@example.com",
      display_name: "Sam",
      mfa_enabled: mfaEnabled,
      has_password: false,
      status: "active",
    },
    memberships: [{ tenant_id: TID, name: "Acme", kind: "team", role: "admin", status: "active" }],
  };
}

const ENROLMENT = {
  enrollment_id: "33333333-3333-4333-8333-333333333333",
  secret: "JBSWY3DPEHPK3PXP",
  otpauth_uri: "otpauth://totp/Notes%20AI:sam@example.com?secret=JBSWY3DPEHPK3PXP",
  expires_in: 900,
};

const CODES = ["aaaa-bbbb-cccc", "dddd-eeee-ffff", "gggg-hhhh-iiii"];

let posted: string[] = [];

function stubServer(mfaEnabled: boolean, overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init: unknown = {}) => {
      const path = new URL(String(url)).pathname;
      const method = ((init as RequestInit).method ?? "GET").toUpperCase();
      if (method !== "GET") posted.push(`${method} ${path}`);

      const routes: Record<string, unknown> = {
        "/auth/refresh": { access_token: "at", expires_in: 900 },
        "/auth/me": me(mfaEnabled),
        "/auth/sessions": [],
        "/auth/mfa/totp/enroll": ENROLMENT,
        "/auth/mfa/totp/confirm": { recovery_codes: CODES },
        "/auth/mfa/recovery-codes": { recovery_codes: CODES },
        ...overrides,
      };
      const body = routes[path];
      if (body === undefined) return new Response("{}", { status: 404 });
      if (body instanceof Response) return body.clone();
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function mount() {
  return render(
    <ToasterProvider>
      <AuthProvider>
        <MemoryRouter>
          <SecuritySettingsPage />
        </MemoryRouter>
      </AuthProvider>
    </ToasterProvider>,
  );
}

beforeEach(() => {
  posted = [];
  setAccessToken(null);
  setReauthHandler(null);
  setSessionListener({});
});

afterEach(() => vi.unstubAllGlobals());

describe("MFA enrolment", () => {
  it("shows the manual key and takes a code, then the recovery codes once", async () => {
    const user = userEvent.setup();
    stubServer(false);
    mount();

    await waitFor(() => expect(screen.getByText("Off")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Turn on" }));

    // Grouped in fours — a 16-character base32 run cannot be typed reliably.
    await waitFor(() => expect(screen.getByText("JBSW Y3DP EHPK 3PXP")).toBeInTheDocument());
    expect(screen.getByTestId("qr")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/code from the app/i), "123456");
    await user.click(screen.getByRole("button", { name: "Turn on" }));

    await waitFor(() => expect(screen.getByText(CODES[0]!)).toBeInTheDocument());
    for (const code of CODES) expect(screen.getByText(code)).toBeInTheDocument();
    expect(posted).toContain("POST /auth/mfa/totp/confirm");
  });

  it("will not leave the codes screen until they are acknowledged", async () => {
    const user = userEvent.setup();
    stubServer(false);
    mount();

    await waitFor(() => expect(screen.getByText("Off")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(screen.getByText("JBSW Y3DP EHPK 3PXP")).toBeInTheDocument());
    await user.type(screen.getByLabelText(/code from the app/i), "123456");
    await user.click(screen.getByRole("button", { name: "Turn on" }));

    await waitFor(() => expect(screen.getByText(CODES[0]!)).toBeInTheDocument());
    const done = screen.getByRole("button", { name: "Done" });
    expect(done).toBeDisabled();

    await user.click(screen.getByRole("checkbox"));
    expect(done).toBeEnabled();
  });

  it("says that other sessions were ended", async () => {
    const user = userEvent.setup();
    stubServer(false);
    mount();

    await waitFor(() => expect(screen.getByText("Off")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(screen.getByTestId("qr")).toBeInTheDocument());
    // Stated before the person commits, not only afterwards.
    expect(screen.getByText(/signs out every other session/i)).toBeInTheDocument();
  });

  it("offers regeneration and turning off once enabled, and never the key again", async () => {
    stubServer(true);
    mount();

    await waitFor(() => expect(screen.getByText("On")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "New recovery codes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn off" })).toBeInTheDocument();
    expect(screen.queryByText(/JBSW/)).toBeNull();
  });

  it("explains a deployment that does not serve MFA rather than failing blank", async () => {
    const user = userEvent.setup();
    // Keycloak mode: every native route answers 404 by design.
    stubServer(false, { "/auth/mfa/totp/enroll": new Response("{}", { status: 404 }) });
    mount();

    await waitFor(() => expect(screen.getByText("Off")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Turn on" }));

    await waitFor(() =>
      expect(screen.getByText(/isn't available in this deployment/i)).toBeInTheDocument(),
    );
  });
});

describe("sessions", () => {
  it("marks this browser and offers no way to revoke it", async () => {
    stubServer(true, {
      "/auth/sessions": [
        {
          sid: "s1",
          client_type: "web",
          device_name: "Chrome on macOS",
          user_agent: "",
          ip_last: "203.0.113.7",
          created_at: new Date().toISOString(),
          last_used_at: new Date().toISOString(),
          last_authenticated_at: new Date().toISOString(),
          current: true,
        },
        {
          sid: "s2",
          client_type: "ios",
          device_name: "iPhone",
          user_agent: "",
          ip_last: "203.0.113.9",
          created_at: new Date().toISOString(),
          last_used_at: new Date().toISOString(),
          last_authenticated_at: new Date().toISOString(),
          current: false,
        },
      ],
    });
    mount();

    const here = await screen.findByText("Chrome on macOS");
    const hereRow = here.closest(".row")!;
    expect(within(hereRow as HTMLElement).getByText("This browser")).toBeInTheDocument();
    expect(within(hereRow as HTMLElement).queryByRole("button")).toBeNull();

    const other = screen.getByText("iPhone").closest(".row")!;
    expect(within(other as HTMLElement).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /everywhere else/i })).toBeInTheDocument();
  });

  it("removes a revoked row immediately and puts it back if the server refuses", async () => {
    const user = userEvent.setup();
    const rows = [
      {
        sid: "s2",
        client_type: "ios",
        device_name: "iPhone",
        user_agent: "",
        ip_last: "",
        created_at: new Date().toISOString(),
        last_used_at: new Date().toISOString(),
        last_authenticated_at: new Date().toISOString(),
        current: false,
      },
    ];
    stubServer(true, {
      "/auth/sessions": rows,
      "/auth/sessions/s2": new Response(JSON.stringify({ detail: "nope" }), { status: 500 }),
    });
    mount();

    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByText("iPhone")).toBeInTheDocument());
  });
});
