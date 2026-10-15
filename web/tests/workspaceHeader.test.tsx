import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forgetMyInvitations } from "../src/api/account";
import { setSessionListener } from "../src/api/http";
import type { MeResponse, MyInvitation } from "../src/api/types";
import { WorkspaceFromLink } from "../src/App";
import { AuthProvider, useAuth } from "../src/auth/AuthContext";
import { ToasterProvider } from "../src/components/Toaster";
import { InvitationsPage } from "../src/pages/InvitationsPage";
import { AppShell, WorkspaceMenu } from "../src/shell/AppShell";
import { SpacesProvider } from "../src/spaces/SpacesContext";

/** Phase 1–2 of the web work order: the workspace header, `?ws=` links, and the invitee's own list. */

const SUB = "11111111-1111-4111-8111-111111111111";
const PERSONAL = "22222222-2222-4222-8222-222222222222";
const TEAM = "33333333-3333-4333-8333-333333333333";
const STRANGER = "99999999-9999-4999-8999-999999999999";

function meFor(tid: string, teamRole: string | null = "admin"): MeResponse {
  return {
    claims: { sub: SUB, tid, roles: ["owner"] },
    db_user: null,
    identity: { id: SUB, email: "sam@example.com", display_name: "Sam", mfa_enabled: false, has_password: false, status: "active" },
    memberships: [
      { tenant_id: PERSONAL, name: "Sam", kind: "personal", role: "owner", status: "active" },
      ...(teamRole ? [{ tenant_id: TEAM, name: "Sunrise Studio", kind: "team", role: teamRole, status: "active" }] : []),
    ],
    personal_tenant_id: PERSONAL,
  };
}

type Reply = { status?: number; body?: unknown } | undefined;
type Call = { method: string; path: string; body: Record<string, unknown> | null };

function serve(me: MeResponse, handler: (c: Call) => Reply = () => undefined) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : null;
      const call = { method, path, body };
      calls.push(call);
      let reply = handler(call);
      if (!reply) {
        if (path === "/auth/refresh") reply = { body: { access_token: "at-start", expires_in: 900, tenant_id: me.claims.tid } };
        else if (path === "/auth/me") reply = { body: me };
        else if (path === "/v1/notifications/unread-count") reply = { body: { unread_count: 0 } };
        else if (path === "/v1/spaces") reply = { body: { spaces: [] } };
        else reply = { body: { items: [] } };
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
  const { activeTenantId } = useAuth();
  return (
    <div data-testid="where">
      {loc.pathname}
      {loc.search}|{activeTenantId}
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

function header(collapsed = false) {
  return <Route path="/" element={<><WorkspaceMenu collapsed={collapsed} /><Where /></>} />;
}

beforeEach(() => {
  setSessionListener({});
  forgetMyInvitations();
});
afterEach(() => vi.unstubAllGlobals());

describe("workspace header", () => {
  it("says Personal, with the role under it, for a personal workspace", async () => {
    serve(meFor(PERSONAL));
    mount("/", header());
    const head = await screen.findByRole("button", { name: /^Personal/ });
    expect(head).toHaveTextContent("Owner");
    expect(head.querySelector(".sb-ws-mark.personal svg")).not.toBeNull();
  });

  it("names a team workspace and the role in it", async () => {
    serve(meFor(TEAM, "admin"));
    mount("/", header());
    const head = await screen.findByRole("button", { name: /^Sunrise Studio/ });
    expect(head).toHaveTextContent("Admin");
  });

  it("opens the switcher with only one workspace", async () => {
    serve(meFor(PERSONAL, null));
    mount("/", header());
    await userEvent.click(await screen.findByRole("button", { name: /^Personal/ }));
    const menu = await screen.findByRole("menu", { name: "Workspaces" });
    expect(within(menu).getByRole("menuitem", { name: "New workspace…" })).toBeInTheDocument();
  });

  it("collapsed: a first letter in a circle, the name as the tooltip", async () => {
    serve(meFor(TEAM, "member"));
    mount("/", header(true));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(TEAM));
    const head = screen.getByTitle("Sunrise Studio");
    expect(head.querySelector(".sb-ws-mark")).toHaveTextContent(/^S$/);
    expect(head).not.toHaveTextContent("Member");
  });
});

describe("?ws= deep links", () => {
  function Note() {
    return <div data-testid="note">note loaded</div>;
  }
  /** `RequireAuth`'s part: nothing below renders until the session is restored. */
  function Signed({ children }: { children: ReactNode }) {
    return useAuth().status === "authenticated" ? <>{children}</> : null;
  }
  const route = (
    <Route
      path="/notes/:noteId"
      element={
        <Signed>
          <WorkspaceFromLink>
            <Note />
            <Where />
          </WorkspaceFromLink>
        </Signed>
      }
    />
  );

  it("a member's link switches first, then opens the note", async () => {
    const calls = serve(meFor(PERSONAL), (c) =>
      c.path === "/auth/token" ? { body: { access_token: "at-team", expires_in: 900, tenant_id: TEAM, roles: ["admin"] } } : undefined,
    );
    mount(`/notes/n1?ws=${TEAM}`, route);
    expect(await screen.findByTestId("note")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(`/notes/n1|${TEAM}`);
    expect(calls.find((c) => c.path === "/auth/token")?.body).toMatchObject({ tenant_id: TEAM, activate: true });
    // Nothing was read before the switch.
    const first = calls.findIndex((c) => c.path === "/auth/token");
    expect(calls.slice(0, first).some((c) => c.path.startsWith("/v1/"))).toBe(false);
  });

  it("a link to a workspace you are not in says so, with the switcher", async () => {
    const calls = serve(meFor(PERSONAL), (c) => {
      if (c.path !== "/auth/token") return undefined;
      return c.body?.tenant_id === STRANGER
        ? { status: 403, body: { code: "not_a_member" } }
        : { body: { access_token: "at-team", expires_in: 900, tenant_id: TEAM, roles: ["admin"] } };
    });
    mount(`/notes/n1?ws=${STRANGER}`, route);
    expect(await screen.findByText("You are not a member of that workspace.")).toBeInTheDocument();
    expect(screen.queryByTestId("note")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open in Sunrise Studio" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/auth/token").at(-1)?.body).toMatchObject({ tenant_id: TEAM }));
  });
});

describe("invitations to me", () => {
  const INVITE: MyInvitation = {
    id: "inv-1",
    workspace_name: "Globex",
    inviter_display: "Anna",
    role: "member",
    expires_at: new Date(Date.now() + 7 * 86400_000).toISOString(),
  };

  it("lists them; Accept moves the session there, Decline closes one", async () => {
    let open = [INVITE, { ...INVITE, id: "inv-2", workspace_name: "Initech" }];
    const calls = serve(meFor(PERSONAL), (c) => {
      if (c.path === "/auth/invitations" && c.method === "GET") return { body: { items: open } };
      if (c.path === "/auth/invitations/inv-2/decline") {
        open = open.filter((i) => i.id !== "inv-2");
        return { status: 204 };
      }
      if (c.path === "/auth/invitations/inv-1/accept")
        return { body: { tenant_id: TEAM, role: "member", token: { access_token: "at-g", expires_in: 900, tenant_id: TEAM, roles: ["member"] } } };
      return undefined;
    });
    mount("/invitations", <Route path="/invitations" element={<InvitationsPage />} />);
    expect(await screen.findByText("Initech")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Decline" })[1]!);
    await waitFor(() => expect(screen.queryByText("Initech")).toBeNull());

    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/|${TEAM}`));
    expect(calls.some((c) => c.path === "/auth/invitations/inv-1/accept")).toBe(true);
  });

  it("the account menu shows Invitations (n), read once per five minutes however often the window is focused", async () => {
    const calls = serve(meFor(PERSONAL), (c) =>
      c.path === "/auth/invitations" ? { body: { items: [INVITE] } } : undefined,
    );
    function Shell() {
      return (
        <SpacesProvider>
          <AppShell />
        </SpacesProvider>
      );
    }
    mount("/", <Route path="/" element={<Shell />} />);
    const account = await screen.findByTitle("Account menu");
    await waitFor(() => expect(account.querySelector(".avatar-dot")).not.toBeNull());
    await userEvent.click(account);
    expect(screen.getByRole("menuitem", { name: "Invitations (1)" })).toBeInTheDocument();

    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("focus"));
    await new Promise((r) => setTimeout(r, 20));
    expect(calls.filter((c) => c.path === "/auth/invitations")).toHaveLength(1);
  });
});
