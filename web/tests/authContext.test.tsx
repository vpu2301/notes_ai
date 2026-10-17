import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "../src/auth/AuthContext";
import { api, refreshSession, setSessionListener, setWorkspaceMoved, WorkspaceMovedError } from "../src/api/http";
import type { AuthResult, MeResponse } from "../src/api/types";
import { WorkspaceMovedStrip } from "../src/shell/AppShell";
import { listTenants } from "../src/api/account";

/** The context exposes one `identity` shape whether the server sends `identity` or only `db_user`. */

const CLAIMS = {
  sub: "11111111-1111-4111-8111-111111111111",
  tid: "22222222-2222-4222-8222-222222222222",
  roles: ["member"],
};

function probe() {
  function Probe() {
    const { status, identity, displayName, memberships, activeTenantId, activeRole } = useAuth();
    return (
      <div>
        <span data-testid="status">{status}</span>
        <span data-testid="name">{displayName}</span>
        <span data-testid="email">{identity?.email ?? "—"}</span>
        <span data-testid="workspaces">{memberships.map((m) => m.name).join(",")}</span>
        <span data-testid="tenant">{activeTenantId ?? "—"}</span>
        <span data-testid="role">{activeRole ?? "—"}</span>
      </div>
    );
  }
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

function stubFetch(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const path = new URL(String(url)).pathname;
      const body = routes[path];
      if (body === undefined) return new Response("{}", { status: 404 });
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

beforeEach(() => setSessionListener({}));
afterEach(() => vi.unstubAllGlobals());

describe("identity hydration", () => {
  it("prefers the identity the server sends", async () => {
    const me: MeResponse = {
      claims: CLAIMS,
      db_user: null,
      identity: {
        id: CLAIMS.sub,
        email: "sam@example.com",
        display_name: "Sam Rivera",
        mfa_enabled: true,
        has_password: false,
        status: "active",
      },
      memberships: [
        { tenant_id: CLAIMS.tid, name: "Acme", kind: "team", role: "member", status: "active" },
      ],
    };
    stubFetch({ "/auth/refresh": { access_token: "at", expires_in: 900 }, "/auth/me": me });
    probe();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("name")).toHaveTextContent("Sam Rivera");
    expect(screen.getByTestId("email")).toHaveTextContent("sam@example.com");
    expect(screen.getByTestId("workspaces")).toHaveTextContent("Acme");
    expect(screen.getByTestId("role")).toHaveTextContent("member");
  });

  it("derives one from db_user while /auth/me is still the old shape", async () => {
    // The shell must render identically.
    const me: MeResponse = {
      claims: CLAIMS,
      db_user: {
        sub: CLAIMS.sub,
        tenant_id: CLAIMS.tid,
        email: "sam@example.com",
        display_name: "Sam Rivera",
        role: "member",
        status: "active",
        mfa_enrolled_at: "2026-09-01T10:00:00Z",
        last_login_at: null,
      },
    };
    stubFetch({ "/auth/refresh": { access_token: "at", expires_in: 900 }, "/auth/me": me });
    probe();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("name")).toHaveTextContent("Sam Rivera");
    expect(screen.getByTestId("email")).toHaveTextContent("sam@example.com");
    expect(screen.getByTestId("tenant")).toHaveTextContent(CLAIMS.tid);
    // No `memberships` here: the role must come from the `users` row.
    expect(screen.getByTestId("role")).toHaveTextContent("member");
  });

  it("falls back to the address when there is no display name", async () => {
    const me: MeResponse = {
      claims: CLAIMS,
      db_user: null,
      identity: {
        id: CLAIMS.sub,
        email: "sam@example.com",
        display_name: "",
        mfa_enabled: false,
        has_password: false,
        status: "active",
      },
    };
    stubFetch({ "/auth/refresh": { access_token: "at", expires_in: 900 }, "/auth/me": me });
    probe();

    await waitFor(() => expect(screen.getByTestId("name")).toHaveTextContent("sam@example.com"));
  });

  it("stays anonymous when the boot refresh fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    probe();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    expect(screen.getByTestId("email")).toHaveTextContent("—");
  });
});

describe("AuthResult handling", () => {
  const mfaRequired: AuthResult = {
    status: "mfa_required",
    access_token: "",
    expires_in: 300,
    tenant_id: "",
    roles: [],
    is_new_identity: false,
    identity: null,
    memberships: [],
    default_tenant_id: null,
    challenge_id: "33333333-3333-4333-8333-333333333333",
    methods: ["totp", "recovery_code"],
    recovery_codes_left: null,
    recovery_codes_exhausted: null,
  };

  it("does not sign anyone in on an mfa_required result", async () => {
    // A 200 with an empty access_token is not a session (MFA second factor).
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));

    let adopt!: (r: AuthResult) => Promise<unknown>;
    function Grab() {
      const auth = useAuth();
      adopt = auth.adopt;
      return <span data-testid="status">{auth.status}</span>;
    }
    render(
      <AuthProvider>
        <Grab />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));

    let outcome: unknown;
    await act(async () => {
      outcome = await adopt(mfaRequired);
    });
    expect(outcome).toEqual({
      kind: "mfa_required",
      challengeId: mfaRequired.challenge_id,
      methods: ["totp", "recovery_code"],
      expiresIn: 300,
    });
    expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
  });
});

describe("step-up gate", () => {
  it("resolves the waiting request when the dialog succeeds, rejects when cancelled", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));

    let ctx!: ReturnType<typeof useAuth>;
    function Grab() {
      ctx = useAuth();
      return <span data-testid="pending">{String(ctx.reauthPending)}</span>;
    }
    render(
      <AuthProvider>
        <Grab />
      </AuthProvider>,
    );
    // Let the boot refresh settle first.
    await waitFor(() => expect(screen.getByTestId("pending")).toHaveTextContent("false"));

    let accepted!: Promise<void>;
    act(() => {
      accepted = ctx.reauth();
    });
    expect(screen.getByTestId("pending")).toHaveTextContent("true");
    act(() => ctx.resolveReauth(true));
    await expect(accepted).resolves.toBeUndefined();
    expect(screen.getByTestId("pending")).toHaveTextContent("false");

    let declined!: Promise<void>;
    act(() => {
      declined = ctx.reauth();
    });
    expect(screen.getByTestId("pending")).toHaveTextContent("true");
    act(() => ctx.resolveReauth(false));
    await expect(declined).rejects.toThrow("reauth cancelled");
  });
});

describe("anonymous routes", () => {
  it("never calls /auth/refresh on a shared link or the join page", async () => {
    const { isAnonymousRoute } = await import("../src/auth/AuthContext");
    expect(isAnonymousRoute("/s/" + "t".repeat(43))).toBe(true);
    expect(isAnonymousRoute("/join")).toBe(true);
    expect(isAnonymousRoute("/join/")).toBe(true);
    expect(isAnonymousRoute("/")).toBe(false);
    expect(isAnonymousRoute("/login")).toBe(false);
    expect(isAnonymousRoute("/settings")).toBe(false);
  });

  it("settles to anonymous without a network call when the page is /s/:token", async () => {
    window.history.pushState({}, "", "/s/" + "t".repeat(43));
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    try {
      probe();
      await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
      window.history.pushState({}, "", "/");
    }
  });
});

describe("workspace moved in another tab", () => {
  const OTHER = "33333333-3333-4333-8333-333333333333";
  const me: MeResponse = {
    claims: CLAIMS,
    db_user: null,
    identity: {
      id: CLAIMS.sub,
      email: "sam@example.com",
      display_name: "Sam Rivera",
      mfa_enabled: false,
      has_password: false,
      status: "active",
    },
    memberships: [
      { tenant_id: CLAIMS.tid, name: "Sam", kind: "personal", role: "owner", status: "active" },
      { tenant_id: OTHER, name: "Globex", kind: "team", role: "member", status: "active" },
    ],
  };

  /** Fetch stub whose refresh answer can change mid-test; records every path it saw. */
  function stubSession() {
    const state = { tenant: CLAIMS.tid, paths: [] as string[] };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        const path = new URL(String(url)).pathname;
        state.paths.push(path);
        const body =
          path === "/auth/refresh"
            ? { access_token: `at-${state.tenant}`, expires_in: 900, tenant_id: state.tenant }
            : path === "/auth/me"
              ? me
              : { items: [] };
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    return state;
  }

  function renderShell() {
    function Probe() {
      const { activeTenantId } = useAuth();
      return <span data-testid="tenant">{activeTenantId ?? "—"}</span>;
    }
    return render(
      <AuthProvider>
        <MemoryRouter>
          <Probe />
          <WorkspaceMovedStrip />
        </MemoryRouter>
      </AuthProvider>,
    );
  }

  afterEach(() => setWorkspaceMoved(null));

  it("a refresh into another workspace blocks the next note request and shows the strip", async () => {
    const session = stubSession();
    renderShell();
    await waitFor(() => expect(screen.getByTestId("tenant")).toHaveTextContent(CLAIMS.tid));

    session.tenant = OTHER;
    await act(async () => {
      await refreshSession();
    });

    expect(await screen.findByRole("status")).toHaveTextContent(/switched to Globex in another tab/i);
    // The tab still shows its own workspace: nothing re-scopes silently.
    expect(screen.getByTestId("tenant")).toHaveTextContent(CLAIMS.tid);
    session.paths.length = 0;
    await expect(api("note", "/v1/notes", { method: "POST", json: {} })).rejects.toBeInstanceOf(WorkspaceMovedError);
    expect(session.paths).toEqual([]);
  });

  it("a broadcast from the switching tab does the same without waiting for a refresh", async () => {
    const channels: { onmessage: ((e: MessageEvent) => void) | null }[] = [];
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        onmessage: ((e: MessageEvent) => void) | null = null;
        constructor(readonly name: string) {
          channels.push(this);
        }
        postMessage() {}
        close() {}
      },
    );
    stubSession();
    renderShell();
    await waitFor(() => expect(screen.getByTestId("tenant")).toHaveTextContent(CLAIMS.tid));

    act(() => {
      for (const ch of channels) ch.onmessage?.(new MessageEvent("message", { data: { tenant_id: OTHER } }));
    });

    expect(await screen.findByRole("status")).toHaveTextContent(/switched to Globex/i);
    await expect(api("note", "/v1/notes")).rejects.toBeInstanceOf(WorkspaceMovedError);
  });

  it("ignores its own workspace on the channel (the posting tab hears itself)", async () => {
    const channels: { onmessage: ((e: MessageEvent) => void) | null }[] = [];
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        onmessage: ((e: MessageEvent) => void) | null = null;
        constructor(readonly name: string) {
          channels.push(this);
        }
        postMessage() {}
        close() {}
      },
    );
    stubSession();
    renderShell();
    await waitFor(() => expect(screen.getByTestId("tenant")).toHaveTextContent(CLAIMS.tid));

    act(() => {
      for (const ch of channels) ch.onmessage?.(new MessageEvent("message", { data: { tenant_id: CLAIMS.tid } }));
    });

    expect(screen.queryByRole("status")).toBeNull();
    await expect(api("note", "/v1/notes")).resolves.toEqual({ items: [] });
  });

  it("names a workspace this tab has not heard of from the last GET /tenants", async () => {
    const NEWER = "44444444-4444-4444-8444-444444444444";
    const session = stubSession();
    renderShell();
    await waitFor(() => expect(screen.getByTestId("tenant")).toHaveTextContent(CLAIMS.tid));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        const path = new URL(String(url)).pathname;
        session.paths.push(path);
        const body =
          path === "/auth/refresh"
            ? { access_token: "at-new", expires_in: 900, tenant_id: NEWER }
            : { items: [{ id: NEWER, name: "sunrise", display_name: "Sunrise Studio", kind: "team", my_role: "owner", is_active: true }] };
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    // The switcher read it earlier.
    await listTenants();
    session.paths.length = 0;
    await act(async () => {
      await refreshSession();
    });
    expect(await screen.findByRole("status")).toHaveTextContent(/switched to Sunrise Studio in another tab/i);
    expect(session.paths).toEqual(["/auth/refresh"]);
  });

  it("Continue there adopts the new workspace and lets requests through again", async () => {
    const session = stubSession();
    renderShell();
    await waitFor(() => expect(screen.getByTestId("tenant")).toHaveTextContent(CLAIMS.tid));
    session.tenant = OTHER;
    await act(async () => {
      await refreshSession();
    });
    await screen.findByRole("status");

    fireEvent.click(screen.getByRole("button", { name: /continue there/i }));

    await waitFor(() => expect(screen.getByTestId("tenant")).toHaveTextContent(OTHER));
    expect(screen.queryByRole("status")).toBeNull();
    await expect(api("note", "/v1/notes")).resolves.toEqual({ items: [] });
  });
});
