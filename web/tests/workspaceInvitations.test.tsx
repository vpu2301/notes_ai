import "@testing-library/jest-dom/vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAccessToken, setSessionListener } from "../src/api/http";
import type { AuthResult, InvitationOut, MeResponse, TenantMember } from "../src/api/types";
import { AuthProvider, useAuth } from "../src/auth/AuthContext";
import { ToasterProvider } from "../src/components/Toaster";
import { InvitePage } from "../src/pages/InvitePage";
import { LoginPage } from "../src/pages/LoginPage";
import { MembersSettingsPage } from "../src/pages/settings/MembersSettingsPage";
import { WorkspaceMenu } from "../src/shell/AppShell";

const SUB = "11111111-1111-4111-8111-111111111111";
const PERSONAL = "22222222-2222-4222-8222-222222222222";
const TEAM = "33333333-3333-4333-8333-333333333333";
const NEW = "44444444-4444-4444-8444-444444444444";

function meFor(role: string, tid = TEAM): MeResponse {
  return {
    claims: { sub: SUB, tid, roles: [role] },
    db_user: null,
    identity: { id: SUB, email: "sam@example.com", display_name: "Sam", mfa_enabled: false, has_password: false, status: "active" },
    memberships: [
      { tenant_id: PERSONAL, name: "Sam", kind: "personal", role: "owner", status: "active" },
      { tenant_id: TEAM, name: "Sunrise Studio", kind: "team", role, status: "active" },
    ],
    personal_tenant_id: PERSONAL,
  };
}

function member(sub: string, role: string, extra: Partial<TenantMember> = {}): TenantMember {
  return {
    user_sub: sub,
    role,
    status: "active",
    email: `${sub.slice(0, 4)}@example.com`,
    display_name: null,
    platform_role: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...extra,
  };
}

function invitation(extra: Partial<InvitationOut> = {}): InvitationOut {
  return {
    id: "inv-1",
    email: "tom@client.com",
    role: "member",
    status: "pending",
    expires_at: new Date(Date.now() + 14 * 86400_000).toISOString(),
    sent_count: 1,
    last_sent_at: "2026-10-13T00:00:00Z",
    invited_by_display: "Sam",
    created_at: "2026-10-13T00:00:00Z",
    delivery: "sent",
    ...extra,
  };
}

type Reply = { status?: number; body?: unknown } | undefined;
type Call = { method: string; path: string; body: Record<string, unknown> | null; auth: string | null };

/** A fake auth-service: `handler` answers first, then the signed-in basics. */
function serve(opts: { me?: MeResponse | null; tenant?: string }, handler: (c: Call) => Reply = () => undefined) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : null;
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const call = { method, path, body, auth: headers.Authorization ?? null };
      calls.push(call);
      let reply = handler(call);
      if (!reply) {
        if (path === "/auth/refresh") {
          reply = opts.me
            ? { body: { access_token: "at-start", expires_in: 900, tenant_id: opts.tenant ?? TEAM } }
            : { status: 401, body: { code: "no_refresh_token" } };
        } else if (path === "/auth/me" && opts.me) {
          reply = { body: opts.me };
        } else {
          reply = { body: { items: [] } };
        }
      }
      if (reply.status === 204) return new Response(null, { status: 204 });
      return new Response(JSON.stringify(reply.body ?? {}), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

function Where() {
  const loc = useLocation();
  const { activeTenantId, joinedWorkspace } = useAuth();
  return (
    <div data-testid="where">
      {loc.pathname}
      {loc.search}|{activeTenantId}|{joinedWorkspace ?? ""}
    </div>
  );
}

function mount(path: string, routes: ReactNode) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <ToasterProvider>
          <Routes>
            {routes}
            <Route path="*" element={<Where />} />
          </Routes>
        </ToasterProvider>
      </MemoryRouter>
    </AuthProvider>,
  );
}

const members = <Route path="/settings/members" element={<MembersSettingsPage />} />;

beforeEach(() => setSessionListener({}));
afterEach(() => vi.unstubAllGlobals());

describe("members page", () => {
  it("an invitation lands in Pending", async () => {
    const calls = serve({ me: meFor("admin") }, (c) => {
      if (c.method === "POST" && c.path === `/tenants/${TEAM}/invitations`) return { status: 201, body: invitation() };
      if (c.path === `/tenants/${TEAM}/members`) return { body: { items: [member(SUB, "admin")], seat_meter: { active: 1, limit: 3 } } };
      return undefined;
    });
    mount("/settings/members", members);
    await userEvent.type(await screen.findByRole("textbox", { name: "Email" }), "tom@client.com");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));

    const pending = await screen.findByLabelText("Pending invitations");
    expect(within(pending).getByText("tom@client.com")).toBeInTheDocument();
    expect(within(pending).getByText(/sent 1×/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/invitations"))?.body).toMatchObject({
      email: "tom@client.com",
      role: "member",
    });
    expect(screen.getByText(/1 of 3 free seats/)).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Seats used" })).toHaveAttribute("aria-valuenow", "1");
    expect(within(screen.getByLabelText("Invitation results")).getByText("Sent")).toBeInTheDocument();
  });

  it("says plainly when the address is already a member", async () => {
    serve({ me: meFor("owner") }, (c) =>
      c.method === "POST" && c.path.endsWith("/invitations")
        ? { status: 409, body: { code: "already_member", detail: "internal" } }
        : undefined,
    );
    mount("/settings/members", members);
    await userEvent.type(await screen.findByRole("textbox", { name: "Email" }), "anna@acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    const results = await screen.findByLabelText("Invitation results");
    expect(within(results).getByText("anna@acme.com")).toBeInTheDocument();
    expect(within(results).getByText("That person is already in this workspace.")).toBeInTheDocument();
    expect(screen.queryByText(/internal/)).toBeNull();
  });

  it("resends and revokes a pending invitation", async () => {
    const calls = serve({ me: meFor("admin") }, (c) => {
      if (c.path === `/tenants/${TEAM}/invitations` && c.method === "GET") return { body: { items: [invitation()] } };
      if (c.path.endsWith("/inv-1/resend")) return { body: invitation({ sent_count: 2 }) };
      if (c.method === "DELETE" && c.path.endsWith("/invitations/inv-1")) return { status: 204 };
      return undefined;
    });
    mount("/settings/members", members);
    const pending = await screen.findByLabelText("Pending invitations");
    await userEvent.click(within(pending).getByRole("button", { name: "Resend" }));
    expect(await within(pending).findByText(/sent 2×/)).toBeInTheDocument();

    await userEvent.click(within(pending).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(screen.queryByLabelText("Pending invitations")).toBeNull());
    expect(calls.some((c) => c.method === "DELETE" && c.path === `/tenants/${TEAM}/invitations/inv-1`)).toBe(true);
  });

  it("shows a Left row with its date and no actions", async () => {
    serve({ me: meFor("owner") }, (c) =>
      c.path === `/tenants/${TEAM}/members`
        ? {
            body: {
              items: [member(SUB, "owner"), member("bbbb", "member", { status: "suspended", left_at: "2026-10-10T09:00:00Z" })],
            },
          }
        : undefined,
    );
    mount("/settings/members", members);
    expect(await screen.findByText(/^Left /)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("will not let the last owner leave, and says why", async () => {
    serve({ me: meFor("owner") }, (c) =>
      c.path === `/tenants/${TEAM}/members` ? { body: { items: [member(SUB, "owner"), member("bbbb", "member")] } } : undefined,
    );
    mount("/settings/members", members);
    expect(await screen.findByText(/only owner, so you can't leave/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave…" })).toBeDisabled();
    // Someone else is still in it: Delete offers Archive, and deleting itself waits.
    await userEvent.click(screen.getByRole("button", { name: "Delete…" }));
    const offer = screen.getByRole("alertdialog", { name: /archive .* instead/i });
    expect(within(offer).getByRole("button", { name: "Delete anyway…" })).toBeDisabled();
    expect(within(offer).getByRole("button", { name: "Archive instead" })).toBeEnabled();
  });

  it("a member leaves and lands in Personal", async () => {
    const calls = serve({ me: meFor("member") }, (c) => {
      if (c.path === `/tenants/${TEAM}/members`) return { body: { items: [member(SUB, "member"), member("aaaa", "owner")] } };
      if (c.method === "DELETE" && c.path === `/tenants/${TEAM}/members/me`)
        return { body: { token: { access_token: "at-personal", expires_in: 900, tenant_id: PERSONAL, roles: ["owner"] } } };
      return undefined;
    });
    mount("/settings/members", members);
    // A member neither invites nor sees the danger zone.
    await screen.findByText("In this workspace");
    expect(screen.queryByRole("textbox", { name: "Email" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete…" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive…" })).toBeNull();

    await userEvent.click(await screen.findByRole("button", { name: "Leave…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Leave" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/|${PERSONAL}|`));
    expect(getAccessToken()).toBe("at-personal");
    expect(calls.some((c) => c.method === "DELETE" && c.path.endsWith("/members/me"))).toBe(true);
  });

  it("delete offers archive first, and archiving lands in Personal", async () => {
    const calls = serve({ me: meFor("owner") }, (c) => {
      if (c.path === `/tenants/${TEAM}/members`) return { body: { items: [member(SUB, "owner"), member("bbbb", "member")] } };
      if (c.path === `/tenants/${TEAM}/archive`)
        return { body: { status: "archived", token: { access_token: "at-personal", expires_in: 900, tenant_id: PERSONAL, roles: ["owner"] } } };
      return undefined;
    });
    mount("/settings/members", members);
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete…" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Delete…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Archive instead" }));

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/|${PERSONAL}|`));
    expect(getAccessToken()).toBe("at-personal");
    expect(calls.some((c) => c.method === "POST" && c.path === `/tenants/${TEAM}/archive`)).toBe(true);
    expect(calls.some((c) => c.path.endsWith("/dissolve"))).toBe(false);
  });

  it("dissolve needs the exact name typed", async () => {
    const calls = serve({ me: meFor("owner") }, (c) => {
      if (c.path === `/tenants/${TEAM}/members`) return { body: { items: [member(SUB, "owner")] } };
      if (c.path === `/tenants/${TEAM}/dissolve`) return { status: 202, body: { status: "dissolved", restore_until: "2026-11-12T00:00:00Z" } };
      if (c.path === "/auth/token") return { body: { access_token: "at-personal", expires_in: 900, tenant_id: PERSONAL, roles: ["owner"] } };
      return undefined;
    });
    mount("/settings/members", members);
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete…" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Delete…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete anyway…" }));
    const dialog = screen.getByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "Delete" });
    expect(confirm).toBeDisabled();
    const input = within(dialog).getByRole("textbox");
    await userEvent.type(input, "sunrise studio");
    expect(confirm).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "Sunrise Studio");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/|${PERSONAL}|`));
    expect(calls.find((c) => c.path.endsWith("/dissolve"))?.body).toEqual({ confirm_name: "Sunrise Studio" });
    expect(calls.find((c) => c.path === "/auth/token")?.body).toMatchObject({ tenant_id: PERSONAL, activate: true });
  });
});

describe("members page — invite form and roster rules", () => {
  it("a step-up 403 opens the reauth prompt and the invitation then goes through", async () => {
    let posts = 0;
    const calls = serve({ me: meFor("admin") }, (c) => {
      if (c.method === "POST" && c.path === `/tenants/${TEAM}/invitations`) {
        posts += 1;
        return posts === 1 ? { status: 403, body: { code: "reauth_required" } } : { status: 201, body: invitation() };
      }
      return undefined;
    });
    let prompted = false;
    function AutoProve() {
      const { reauthPending, resolveReauth } = useAuth();
      if (reauthPending) {
        prompted = true;
        queueMicrotask(() => resolveReauth(true));
      }
      return null;
    }
    mount("/settings/members", <Route path="/settings/members" element={<><MembersSettingsPage /><AutoProve /></>} />);
    await userEvent.type(await screen.findByRole("textbox", { name: "Email" }), "tom@client.com");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    expect(await screen.findByLabelText("Pending invitations")).toHaveTextContent("tom@client.com");
    expect(prompted).toBe(true);
    expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/invitations"))).toHaveLength(2);
  });

  it("sends one invitation per chip, in order, and reports each address", async () => {
    const calls = serve({ me: meFor("admin") }, (c) => {
      if (c.method !== "POST" || !c.path.endsWith("/invitations")) return undefined;
      return c.body?.email === "bad@client.com"
        ? { status: 503, body: { code: "invite_unavailable" } }
        : { status: 201, body: invitation({ id: String(c.body?.email), email: String(c.body?.email) }) };
    });
    mount("/settings/members", members);
    await userEvent.type(await screen.findByRole("textbox", { name: "Email" }), "a@client.com, bad@client.com b@client.com");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    const results = await screen.findByLabelText("Invitation results");
    expect(within(results).getAllByRole("listitem")).toHaveLength(3);
    expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/invitations")).map((c) => c.body?.email)).toEqual([
      "a@client.com",
      "bad@client.com",
      "b@client.com",
    ]);
    // The one that failed stays in the box for another try.
    expect(screen.getByRole("button", { name: "Remove bad@client.com" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove a@client.com" })).toBeNull();
  });

  it("marks what is not an address and sends nothing", async () => {
    const calls = serve({ me: meFor("admin") });
    mount("/settings/members", members);
    await userEvent.type(await screen.findByRole("textbox", { name: "Email" }), "tom@client.com tom-at-client ");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    expect(await screen.findByText(/“tom-at-client” doesn’t look like an e-mail address/)).toBeInTheDocument();
    expect(screen.getByText("tom-at-client").closest(".recipient-chip")).toHaveClass("invalid");
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/invitations"))).toBe(false);
  });

  it("counts the message against its 500 characters", async () => {
    serve({ me: meFor("admin") });
    mount("/settings/members", members);
    await userEvent.click(await screen.findByRole("button", { name: "Add a message" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "Welcome");
    expect(screen.getByText("7 / 500")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveAttribute("maxlength", "500");
  });

  it("right after New workspace… it offers to invite later", async () => {
    serve({ me: meFor("owner") });
    mount("/settings/members?first=1", members);
    expect(await screen.findByText("Invite your first teammate")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "You can do this later" }));
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/\|/);
  });

  it("an owner can make someone an owner; an admin is not offered that, nor an owner's row", async () => {
    const roster = { body: { items: [member(SUB, "owner"), member("bbbb", "member"), member("cccc", "owner")] } };
    serve({ me: meFor("owner") }, (c) => (c.path === `/tenants/${TEAM}/members` ? roster : undefined));
    const view = mount("/settings/members", members);
    await userEvent.click(await screen.findByRole("button", { name: "Role for bbbb@example.com" }));
    expect(screen.getByRole("menuitemradio", { name: "Owner" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Role for cccc@example.com" })).toBeInTheDocument();
    view.unmount();

    const adminRoster = { body: { items: [member(SUB, "admin"), member("bbbb", "member"), member("cccc", "owner")] } };
    serve({ me: meFor("admin") }, (c) => (c.path === `/tenants/${TEAM}/members` ? adminRoster : undefined));
    mount("/settings/members", members);
    await userEvent.click(await screen.findByRole("button", { name: "Role for bbbb@example.com" }));
    expect(screen.queryByRole("menuitemradio", { name: "Owner" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Role for cccc@example.com" })).toBeNull();
  });

  it("keeps the server's last-owner refusal on the row as its tooltip", async () => {
    const roster = { body: { items: [member(SUB, "owner"), member("cccc", "owner")] } };
    serve({ me: meFor("owner") }, (c) => {
      if (c.path === `/tenants/${TEAM}/members`) return roster;
      if (c.method === "PATCH") return { status: 409, body: { detail: "cannot demote the last owner of the tenant" } };
      return undefined;
    });
    mount("/settings/members", members);
    await userEvent.click(await screen.findByRole("button", { name: "Role for cccc@example.com" }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Member" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Role for cccc@example.com" }).closest(".row")).toHaveAttribute(
        "title",
        "A workspace needs at least one owner.",
      ),
    );
  });
});

describe("invite landing", () => {
  const LOOKUP = {
    workspace_name: "Sunrise Studio",
    inviter_display: "Anna",
    role: "member",
    email_masked: "t•••@client.com",
    expires_at: "2026-10-27T00:00:00Z",
    note_title: null,
  };
  const invite = <Route path="/invite/:token" element={<InvitePage />} />;

  it("signed out: continue goes to sign-in carrying next (and the address when the link has it)", async () => {
    serve({ me: null }, (c) => (c.path === "/auth/invitations/tok" ? { body: LOOKUP } : undefined));
    mount("/invite/tok?email=tom%40client.com", invite);
    expect(await screen.findByText(/Anna invited you to/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue with t•••@client.com" }));

    const where = screen.getByTestId("where").textContent ?? "";
    const query = new URLSearchParams(where.slice(where.indexOf("?"), where.indexOf("|")));
    expect(where.startsWith("/login?")).toBe(true);
    expect(query.get("next")).toBe("/invite/tok?accept=1");
    expect(query.get("email")).toBe("tom@client.com");
  });

  it("the sign-in page pre-fills a read-only address for an invitation", async () => {
    serve({ me: null });
    mount("/login?email=tom%40client.com&next=%2Finvite%2Ftok%3Faccept%3D1", <Route path="/login" element={<LoginPage />} />);
    const field = await screen.findByLabelText("Email");
    expect(field).toHaveValue("tom@client.com");
    expect(field).toHaveAttribute("readonly");
  });

  it("signed in as someone else: the mismatch screen, nothing granted", async () => {
    const calls = serve({ me: meFor("member", PERSONAL), tenant: PERSONAL }, (c) => {
      if (c.path === "/auth/invitations/tok") return { body: LOOKUP };
      if (c.path === "/auth/invitations/tok/accept") return { status: 403, body: { code: "invitation_email_mismatch" } };
      return undefined;
    });
    mount("/invite/tok", invite);
    await userEvent.click(await screen.findByRole("button", { name: "Join Sunrise Studio" }));
    expect(await screen.findByText(/You're signed in as/)).toHaveTextContent("sam@example.com");
    expect(screen.getByRole("button", { name: "Sign out and continue" })).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/auth/token")).toBe(false);
  });

  it("back from sign-in it accepts, adopts the token and lands home with the banner", async () => {
    const calls = serve({ me: meFor("member", PERSONAL), tenant: PERSONAL }, (c) => {
      if (c.path === "/auth/invitations/tok") return { body: LOOKUP };
      if (c.path === "/auth/invitations/tok/accept")
        return {
          body: { tenant_id: NEW, role: "member", token: { access_token: "at-new", expires_in: 900, tenant_id: NEW, roles: ["member"] } },
        };
      return undefined;
    });
    mount("/invite/tok?accept=1", invite);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/|${NEW}|Sunrise Studio`));
    expect(getAccessToken()).toBe("at-new");
    // The profile re-read after the move travels with the new token.
    expect(calls.filter((c) => c.path === "/auth/me").at(-1)?.auth).toBe("Bearer at-new");
  });

  it("an invitation to one note names the note", async () => {
    serve({ me: null }, (c) =>
      c.path === "/auth/invitations/tok" ? { body: { ...LOOKUP, role: "guest", note_title: "Q3 plan" } } : undefined,
    );
    mount("/invite/tok", invite);
    expect(await screen.findByText(/Anna invited you to/)).toHaveTextContent("as a guest to see Q3 plan.");
  });

  it("a dead token gets one neutral screen", async () => {
    serve({ me: null }, (c) =>
      c.path === "/auth/invitations/tok" ? { status: 404, body: { code: "invitation_not_found" } } : undefined,
    );
    mount("/invite/tok", invite);
    expect(await screen.findByText("This invitation is no longer valid")).toBeInTheDocument();
  });
});

describe("workspace switcher", () => {
  it("New workspace… creates, switches and opens Members", async () => {
    const calls = serve({ me: meFor("owner", PERSONAL), tenant: PERSONAL }, (c) => {
      if (c.method === "POST" && c.path === "/tenants")
        return { status: 201, body: { id: NEW, name: "sunrise-studio-x1", display_name: "Sunrise Studio", kind: "team" } };
      if (c.path === "/auth/token") return { body: { access_token: "at-new", expires_in: 900, tenant_id: NEW, roles: ["owner"] } };
      return undefined;
    });
    mount("/", <Route path="/" element={<><WorkspaceMenu collapsed={false} /><Where /></>} />);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(PERSONAL));
    await userEvent.click(screen.getByRole("button", { name: /Personal/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "New workspace…" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Sunrise Studio{Enter}");

    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/settings/members?first=1|${NEW}`));
    expect(calls.find((c) => c.method === "POST" && c.path === "/tenants")?.body).toEqual({ name: "Sunrise Studio" });
    expect(calls.find((c) => c.path === "/auth/token")?.body).toMatchObject({ tenant_id: NEW, activate: true });
  });
});

describe("sign-up that accepted invitations", () => {
  it("raises the joined banner for the landing workspace", async () => {
    // Signed out at first; `/auth/me` answers only once the sign-up has a token.
    serve({ me: null }, (c) => (c.path === "/auth/me" ? { body: meFor("member") } : undefined));
    let adopt: ((r: AuthResult) => Promise<unknown>) | null = null;
    function Grab() {
      adopt = useAuth().adopt;
      return null;
    }
    mount("/x", <Route path="/x" element={<><Grab /><Where /></>} />);
    await waitFor(() => expect(adopt).not.toBeNull());
    await act(async () => {
      await adopt!({
        status: "authenticated",
        access_token: "at-signup",
        expires_in: 900,
        tenant_id: TEAM,
        roles: ["member"],
        is_new_identity: true,
        identity: null,
        memberships: meFor("member").memberships!,
        default_tenant_id: PERSONAL,
        challenge_id: null,
        methods: null,
        recovery_codes_left: null,
        recovery_codes_exhausted: null,
        joined_tenant_ids: [TEAM],
      });
    });
    expect(screen.getByTestId("where")).toHaveTextContent(`|${TEAM}|Sunrise Studio`);
  });
});
