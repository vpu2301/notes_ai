import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "../src/auth/AuthContext";
import { setSessionListener } from "../src/api/http";
import type { AuthResult, MeResponse } from "../src/api/types";

/**
 * §M: "AppShell no longer reads db_user" — which really means the context
 * exposes one `identity` shape regardless of which of the two the server
 * happens to send, so IDX-B2 deleting `db_user` breaks nothing.
 */

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
    // This is today's server. The shell must render identically.
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
    // No `memberships` on this shape — the role has to come from the
    // `users` row, or an owner looks like a stranger in their own workspace.
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
    // A real 200 with an empty access_token. Treating it as a session would
    // let an MFA account past the second factor with only the first.
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
    // Let the boot refresh settle before poking the gate, so its state
    // update is not mistaken for one of ours.
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
