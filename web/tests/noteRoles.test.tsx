import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSessionListener } from "../src/api/http";
import { workspaceLabel, type NoteComment } from "../src/api/types";
import { levelBadgeLabel } from "../src/components/AccessBadge";
import { CommentsPanel, NOTE_ANCHOR } from "../src/components/CommentsPanel";
import { presenceLabel } from "../src/components/PresenceAvatars";
import { ShareDialog, inviteSummary } from "../src/components/ShareDialog";
import { ToasterProvider } from "../src/components/Toaster";
import { canCommentNote, canEditNote, canManageNote, readOnlyStrip } from "../src/lib/noteLevel";
import { NoteEditorPage } from "../src/pages/NoteEditorPage";
import { NotesPage } from "../src/pages/NotesPage";
import { SettingsLayout } from "../src/pages/settings/SettingsLayout";
import { AppShell, WorkspaceMenu } from "../src/shell/AppShell";
import { SpacesProvider } from "../src/spaces/SpacesContext";

/** W3 on the web: share by role, levels in the editor, comments, scopes, the guest shell. */

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => auth.value,
  useAuthOptional: () => auth.value,
}));

const ME = "11111111-1111-4111-8111-111111111111";
const ANNA = "55555555-5555-4555-8555-555555555555";
const TOM = "66666666-6666-4666-8666-666666666666";
const TEAM = "33333333-3333-4333-8333-333333333333";
const PERSONAL = "22222222-2222-4222-8222-222222222222";
const NOTE = "77777777-7777-4777-8777-777777777777";

function signedIn(role: string) {
  auth.value = {
    status: "authenticated",
    me: { claims: { sub: ME, tid: TEAM, roles: [role], iss: "http://auth" }, personal_tenant_id: PERSONAL },
    identity: { id: ME, email: "sam@example.com", display_name: "Sam" },
    memberships: [
      { tenant_id: PERSONAL, name: "Sam", kind: "personal", role: "owner", status: "active" },
      { tenant_id: TEAM, name: "Acme Inc", kind: "team", role, status: "active" },
    ],
    activeTenantId: TEAM,
    activeRole: role,
    canSwitchWorkspaces: true,
    displayName: "Sam",
    switchWorkspace: vi.fn(),
    joinedWorkspace: null,
    dismissJoined: vi.fn(),
    workspaceMoved: null,
    followWorkspace: vi.fn(),
    logout: vi.fn(),
  };
}

type Reply = { status?: number; body?: unknown };
type Call = { method: string; path: string; query: URLSearchParams; body: Record<string, unknown> | undefined };

/** A fake backend: `routes` by "METHOD /path" or "/path"; anything else is a 404. */
function server(routes: Record<string, Reply | ((c: Call) => Reply)>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const u = new URL(String(url));
      const method = (init?.method ?? "GET").toUpperCase();
      const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
      const call = { method, path: u.pathname, query: u.searchParams, body };
      calls.push(call);
      const route = routes[`${method} ${u.pathname}`] ?? routes[u.pathname];
      const reply = typeof route === "function" ? route(call) : route;
      if (!reply) return new Response(JSON.stringify({ code: "not_found" }), { status: 404 });
      if (reply.status === 204) return new Response(null, { status: 204 });
      return new Response(JSON.stringify(reply.body ?? {}), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

beforeEach(() => {
  setSessionListener({});
  signedIn("member");
});
afterEach(() => vi.unstubAllGlobals());

// ── share dialog ──────────────────────────────────────────────────────

const SHARING = {
  note_id: NOTE,
  visibility: "private",
  can_manage: true,
  can_delete: true,
  shared_with: [],
  public_link: null,
  links: [],
  constraints: {
    external_links_enabled: true,
    public_links_enabled: true,
    max_link_days: 180,
    product_email_enabled: true,
    verified_recipients_required: false,
  },
  my_level: "manage",
  people: [
    { sub: ME, email: "sam@example.com", display_name: "Sam", level: "manage", source: "author", membership_role: "member", can_change: false },
    { sub: ANNA, email: "anna@example.com", display_name: "Anna", level: "comment", source: "collaborator", membership_role: "member", can_change: true },
    { sub: TOM, email: "tom@client.com", display_name: "Tom", level: "view", source: "collaborator", membership_role: "guest", can_change: true },
  ],
  pending: [{ invitation_id: "inv-9", email_masked: "j***@client.com", note_role: "view", expires_at: "2026-10-27T00:00:00Z" }],
  transcript_shared: false,
  workspace_kind: "team",
};

function sheet() {
  return render(
    <ToasterProvider>
      <ShareDialog noteId={NOTE} noteTitle="Acme kickoff" tenantId={TEAM} meSub={ME} onClose={() => {}} />
    </ToasterProvider>,
  );
}

async function invite(addresses: string, role?: RegExp) {
  await userEvent.type(await screen.findByLabelText(/^invite people$/i), addresses);
  if (role) {
    await userEvent.click(screen.getByRole("button", { name: /^role$/i }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: role }));
  }
  await userEvent.click(screen.getByRole("button", { name: /^share$/i }));
}

describe("share dialog — people by role", () => {
  it("lists everyone with access and why, with a Guest badge and the author unchangeable", async () => {
    server({ [`/v1/notes/${NOTE}/sharing`]: { body: SHARING } });
    sheet();
    const list = await screen.findByLabelText(/who has access/i);
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Sam (you)");
    expect(rows[0]).toHaveTextContent("Author");
    expect(within(rows[0] as HTMLElement).queryByRole("button")).toBeNull();
    expect(rows[2]).toHaveTextContent("Guest");
    expect(within(list).getByRole("button", { name: /role for anna/i })).toHaveTextContent("Can comment");
  });

  it("shows the workspace row when the note is open to the workspace", async () => {
    server({ [`/v1/notes/${NOTE}/sharing`]: { body: { ...SHARING, visibility: "workspace" } } });
    sheet();
    const list = await screen.findByLabelText(/who has access/i);
    expect(list).toHaveTextContent("Everyone in the workspace");
    expect(list).toHaveTextContent("Can edit");
  });

  it("changes a collaborator's role with one PUT", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`PUT /v1/notes/${NOTE}/collaborators/${ANNA}`]: { body: SHARING },
    });
    sheet();
    await userEvent.click(await screen.findByRole("button", { name: /role for anna/i }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /can edit/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT" && c.path.endsWith(`/collaborators/${ANNA}`))?.body).toEqual({ role: "edit" }),
    );
  });

  it("removes a collaborator", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`DELETE /v1/notes/${NOTE}/collaborators/${TOM}`]: { status: 204 },
    });
    sheet();
    await userEvent.click(await screen.findByRole("button", { name: /^remove tom$/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path.endsWith(`/collaborators/${TOM}`))).toBe(true));
  });

  it("grants a member the chosen role at once", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`POST /v1/notes/${NOTE}/share`]: { status: 201, body: { kind: "granted", sharing: SHARING } },
    });
    sheet();
    await invite("anna@example.com", /can comment/i);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/share"))?.body).toMatchObject({
        email: "anna@example.com",
        role: "comment",
      }),
    );
    expect(await screen.findByText(/shared with anna@example\.com/i)).toBeInTheDocument();
    expect(calls.some((c) => c.path.includes("/invitations"))).toBe(false);
  });

  it("invites a non-member as a guest of this note through the workspace invitation", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`POST /v1/notes/${NOTE}/share`]: { status: 404, body: { code: "not_a_member", can_invite: true } },
      [`POST /tenants/${TEAM}/invitations`]: { status: 201, body: { id: "inv-10" } },
    });
    sheet();
    await invite("jo@client.com", /can view/i);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === `/tenants/${TEAM}/invitations`)?.body).toMatchObject({
        email: "jo@client.com",
        role: "guest",
        note_id: NOTE,
        note_role: "view",
      }),
    );
    expect(await screen.findByText(/invited jo@client\.com/i)).toBeInTheDocument();
    expect(within(screen.getByLabelText("Share results")).getByText(/invited — they'll sign in to see this note/i)).toBeInTheDocument();
  });

  it("keeps an address that could not be shared and says why", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`POST /v1/notes/${NOTE}/share`]: { status: 404, body: { code: "not_a_member" } },
    });
    sheet();
    await invite("x@nowhere.com");
    expect(await screen.findByText(/did not get access/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove x@nowhere\.com/i })).toBeInTheDocument();
    expect(calls.some((c) => c.path.includes("/invitations"))).toBe(false);
  });

  it("says when the workspace's sharing settings keep an outsider out (can_invite: false)", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`POST /v1/notes/${NOTE}/share`]: { status: 404, body: { code: "not_a_member", can_invite: false } },
    });
    sheet();
    await invite("x@nowhere.com");
    expect(await screen.findByText(/sharing settings don't allow inviting people from outside/i)).toBeInTheDocument();
    expect(calls.some((c) => c.path.includes("/invitations"))).toBe(false);
  });

  it("marks a chip that is not an address and sends nothing", async () => {
    const calls = server({ [`/v1/notes/${NOTE}/sharing`]: { body: SHARING } });
    sheet();
    await invite("anna@example.com nonsense");
    expect(await screen.findByText(/“nonsense” doesn’t look like an e-mail address/)).toBeInTheDocument();
    expect(screen.getByText("nonsense").closest(".recipient-chip")).toHaveClass("invalid");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("puts chips, role, message and Share in that keyboard order", async () => {
    server({ [`/v1/notes/${NOTE}/sharing`]: { body: SHARING } });
    sheet();
    const box = await screen.findByLabelText(/^invite people$/i);
    await userEvent.type(box, "anna@example.com ");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: /^role$/i })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByLabelText(/invitation message/i)).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: /^share$/i })).toHaveFocus();
  });

  it("revokes a pending note invitation", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`DELETE /tenants/${TEAM}/invitations/inv-9`]: { status: 204 },
    });
    sheet();
    const pending = await screen.findByLabelText(/pending invitations/i);
    expect(pending).toHaveTextContent("j***@client.com");
    await userEvent.click(within(pending).getByRole("button", { name: /revoke invitation/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === `/tenants/${TEAM}/invitations/inv-9`)).toBe(true));
  });

  it("toggles Include transcript", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`PUT /v1/notes/${NOTE}/transcript-sharing`]: { body: { ...SHARING, transcript_shared: true } },
    });
    sheet();
    const toggle = await screen.findByRole("checkbox", { name: /include transcript and audio for viewers and commenters/i });
    expect(screen.getByText(/editors and workspace members always see them/i)).toBeInTheDocument();
    expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(calls.find((c) => c.path.endsWith("/transcript-sharing"))?.body).toEqual({ shared: true });
  });

  it("offers no 'Everyone in the workspace' in a personal workspace", async () => {
    server({ [`/v1/notes/${NOTE}/sharing`]: { body: { ...SHARING, workspace_kind: "personal" } } });
    sheet();
    await screen.findByLabelText(/who has access/i);
    expect(screen.queryByRole("radiogroup", { name: /general access/i })).toBeNull();
    expect(screen.queryByRole("radio", { name: /workspace/i })).toBeNull();
  });

  it("General access is Private | Workspace in a team workspace", async () => {
    const calls = server({
      [`/v1/notes/${NOTE}/sharing`]: { body: SHARING },
      [`PUT /v1/notes/${NOTE}/visibility`]: { body: { ...SHARING, visibility: "workspace" } },
    });
    sheet();
    const group = await screen.findByRole("radiogroup", { name: /general access/i });
    expect(within(group).getByRole("radio", { name: "Private" })).toBeChecked();
    await userEvent.click(within(group).getByRole("radio", { name: "Workspace" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/visibility") && c.body?.visibility === "workspace")).toBe(true));
  });

  it("a reader who cannot manage gets the list only", async () => {
    server({
      [`/v1/notes/${NOTE}/sharing`]: { body: { ...SHARING, can_manage: false, my_level: "comment", pending: [] } },
    });
    sheet();
    await screen.findByLabelText(/who has access/i);
    expect(screen.queryByLabelText(/^invite people$/i)).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: /general access/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /role for anna/i })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /include transcript/i })).toBeNull();
    expect(screen.queryByLabelText(/^e-mail address$/i)).toBeNull();
  });

  it("summarises what an invite did", () => {
    expect(inviteSummary(["a@x.com"], [])).toBe("Shared with a@x.com");
    expect(inviteSummary(["a@x.com", "b@x.com"], ["c@y.com"])).toBe("Shared with 2 people · Invited c@y.com");
  });
});

// ── comments panel ────────────────────────────────────────────────────

function comment(extra: Partial<NoteComment> = {}): NoteComment {
  return {
    id: "c1",
    author: { sub: ANNA, display_name: "Anna" },
    anchor_kind: "section",
    anchor_key: "decisions",
    anchor_present: true,
    body: "Is this final?",
    created_at: "2026-10-13T09:00:00Z",
    edited_at: null,
    resolved_at: null,
    resolved_by_display: null,
    can_edit: false,
    can_resolve: false,
    can_delete: false,
    ...extra,
  };
}

function panel(props: Partial<Parameters<typeof CommentsPanel>[0]> = {}) {
  const changes: NoteComment[][] = [];
  render(
    <CommentsPanel
      noteId={NOTE}
      comments={[comment()]}
      error={null}
      onComments={(next) => changes.push(next)}
      canComment
      anchor={NOTE_ANCHOR}
      onAnchor={() => {}}
      labelFor={(kind, key) => (kind === "section" && key === "decisions" ? "Decisions" : "A line")}
      onClose={() => {}}
      {...props}
    />,
  );
  return changes;
}

describe("comments panel", () => {
  it("groups by anchor and offers only what the flags allow", () => {
    panel({
      comments: [
        comment(),
        comment({ id: "c2", body: "Fixed the date", can_edit: true, can_delete: true, can_resolve: true }),
      ],
    });
    const group = screen.getByRole("region", { name: "Decisions" });
    expect(within(group).getAllByRole("article")).toHaveLength(2);
    // Only the second comment carries flags.
    expect(within(group).getAllByRole("button", { name: /^edit$/i })).toHaveLength(1);
    expect(within(group).getAllByRole("button", { name: /^resolve$/i })).toHaveLength(1);
    expect(within(group).getAllByRole("button", { name: /^delete$/i })).toHaveLength(1);
  });

  it("marks a comment whose line was removed", () => {
    panel({ comments: [comment({ anchor_kind: "item", anchor_key: "abcd", anchor_present: false })] });
    expect(screen.getByText(/on a removed line/i)).toBeInTheDocument();
  });

  it("hides resolved comments until asked", async () => {
    panel({ comments: [comment(), comment({ id: "c2", body: "Done", resolved_at: "2026-10-13T10:00:00Z", resolved_by_display: "Sam" })] });
    expect(screen.queryByText("Done")).toBeNull();
    await userEvent.click(screen.getByRole("checkbox", { name: /resolved \(1\)/i }));
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByText(/resolved by sam/i)).toBeInTheDocument();
  });

  it("posts to the chosen anchor", async () => {
    const calls = server({
      [`POST /v1/notes/${NOTE}/comments`]: { status: 201, body: comment({ id: "c9", body: "Agreed" }) },
    });
    const changes = panel({ anchor: { kind: "section", key: "decisions" } });
    expect(screen.getByText(/on decisions/i)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: /^comment$/i }), "Agreed");
    await userEvent.click(screen.getByRole("button", { name: /^comment$/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({ anchor_kind: "section", anchor_key: "decisions", body: "Agreed" }),
    );
    await waitFor(() => expect(changes.at(-1)?.map((c) => c.id)).toEqual(["c1", "c9"]));
  });

  it("resolves through the API and keeps the server's answer", async () => {
    server({
      [`POST /v1/notes/${NOTE}/comments/c1/resolve`]: { body: comment({ resolved_at: "2026-10-13T10:00:00Z", can_resolve: true }) },
    });
    const changes = panel({ comments: [comment({ can_resolve: true })] });
    await userEvent.click(screen.getByRole("button", { name: /^resolve$/i }));
    await waitFor(() => expect(changes.at(-1)?.[0]?.resolved_at).toBe("2026-10-13T10:00:00Z"));
  });

  it("deletes when allowed", async () => {
    const calls = server({ [`DELETE /v1/notes/${NOTE}/comments/c1`]: { status: 204 } });
    const changes = panel({ comments: [comment({ can_delete: true })] });
    await userEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(changes.at(-1)).toEqual([]));
    expect(calls.some((c) => c.method === "DELETE")).toBe(true);
  });

  it("a viewer reads comments but has no compose box", () => {
    panel({ canComment: false });
    expect(screen.getByText("Is this final?")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /^comment$/i })).toBeNull();
  });

  it("says why a refused comment was refused", async () => {
    server({
      [`POST /v1/notes/${NOTE}/comments`]: { status: 403, body: { code: "insufficient_role", required: "comment" } },
    });
    panel();
    await userEvent.type(screen.getByRole("textbox", { name: /^comment$/i }), "Hello");
    await userEvent.click(screen.getByRole("button", { name: /^comment$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/your access to this note does not include that/i);
  });
});

// ── editor levels ─────────────────────────────────────────────────────

function envelope(extra: Record<string, unknown> = {}) {
  return {
    id: NOTE,
    code: "NOTE-2026-00042",
    status: "draft",
    current_version_id: "v1",
    current_version_number: 1,
    primary_author_id: ANNA,
    co_author_ids: [],
    title: "Acme kickoff",
    created_at: "2026-10-13T09:00:00Z",
    updated_at: "2026-10-13T09:00:00Z",
    finalized_at: null,
    cancelled_at: null,
    source_job_id: "job-1",
    content: {
      title: "Acme kickoff",
      template_id: null,
      sections: [
        { section_key: "decisions", title: "Decisions", text: "- Ship on Friday" },
        { section_key: "action_items", title: "Action items", text: "- Anna: send the deck" },
      ],
    },
    my_level: "comment",
    can_read_transcript: false,
    ...extra,
  };
}

function editor(env: Record<string, unknown>, extra: Record<string, Reply> = {}) {
  const calls = server({
    [`/v1/notes/${NOTE}`]: { body: env },
    [`/v1/notes/${NOTE}/sharing`]: { body: { ...SHARING, my_level: env.my_level } },
    [`/v1/notes/${NOTE}/comments`]: { body: { items: [] } },
    [`/v1/notes/${NOTE}/presence`]: { body: { viewers: [{ sub: ANNA, display_name: "Anna" }] } },
    [`POST /v1/notes/${NOTE}/presence`]: { status: 204 },
    "/v1/spaces": { body: { spaces: [] } },
    ...extra,
  });
  render(
    <ToasterProvider>
      <MemoryRouter initialEntries={[`/notes/${NOTE}`]}>
        <SpacesProvider>
          <Routes>
            <Route path="/notes/:noteId" element={<NoteEditorPage />} />
          </Routes>
        </SpacesProvider>
      </MemoryRouter>
    </ToasterProvider>,
  );
  return calls;
}

async function openMenu() {
  await userEvent.click(screen.getByRole("button", { name: /more actions/i }));
}

describe("note editor — levels", () => {
  it("comment: read-only body with a strip, comment buttons, no share, no transcript", async () => {
    const calls = editor(envelope());
    expect(await screen.findByText("You can comment on this note")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit decisions$/i })).toBeNull();
    expect(screen.getByRole("button", { name: /comment on decisions/i })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /comment on this line/i })).toHaveLength(1);
    expect(screen.queryByRole("tab", { name: /transcript/i })).toBeNull();
    expect(screen.queryByRole("tab", { name: /client version/i })).toBeNull();
    await openMenu();
    expect(screen.queryByRole("button", { name: /^share$/i })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /delete note/i })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /copy job id/i })).toBeNull();
    // The transcript the server refused is never probed for.
    expect(calls.some((c) => c.path.startsWith("/asr/"))).toBe(false);
  });

  it("view: a strip, no comment buttons", async () => {
    editor(envelope({ my_level: "view" }));
    expect(await screen.findByText("You can view this note")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /comment on decisions/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /comment on this line/i })).toBeNull();
  });

  it("edit: no strip, the body is editable, sharing is still the manager's", async () => {
    editor(envelope({ my_level: "edit", can_read_transcript: true }));
    expect(await screen.findByRole("button", { name: /^edit decisions$/i })).toBeInTheDocument();
    expect(screen.queryByText(/you can (comment on|view) this note/i)).toBeNull();
    expect(screen.getByRole("tab", { name: /transcript/i })).toBeInTheDocument();
    await openMenu();
    expect(screen.queryByRole("button", { name: /^share$/i })).toBeNull();
  });

  it("manage: Share is offered", async () => {
    editor(envelope({ my_level: "manage", primary_author_id: ME, can_read_transcript: true }));
    await screen.findByRole("button", { name: /^edit decisions$/i });
    expect(screen.getByRole("button", { name: /^share$/i })).toBeInTheDocument();
  });

  it("a 404 on the transcript hides the tab", async () => {
    editor(envelope({ my_level: "edit", can_read_transcript: true }));
    await userEvent.click(await screen.findByRole("tab", { name: /transcript/i }));
    await waitFor(() => expect(screen.queryByRole("tab", { name: /transcript/i })).toBeNull());
    expect(screen.getByRole("tab", { name: /notes/i })).toHaveAttribute("aria-selected", "true");
  });

  it("shows who else is viewing and sends a heartbeat", async () => {
    const calls = editor(envelope());
    expect(await screen.findByRole("status", { name: "Anna is viewing" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/presence"))).toBe(true);
  });

  it("comment: keystrokes never reach PUT /draft", async () => {
    const calls = editor(envelope());
    await screen.findByText("You can comment on this note");
    await userEvent.type(screen.getByLabelText("Note title"), "typed");
    await new Promise((r) => setTimeout(r, 1100));
    expect(screen.getByLabelText("Note title")).toHaveValue("Acme kickoff");
    expect(calls.some((c) => c.method === "PUT" && c.path.endsWith("/draft"))).toBe(false);
    expect(screen.queryByRole("button", { name: /generate/i })).toBeNull();
  });

  it("a hidden tab sends no heartbeat and reads no presence", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    try {
      const calls = editor(envelope());
      await screen.findByText("You can comment on this note");
      await new Promise((r) => setTimeout(r, 20));
      expect(calls.some((c) => c.path.endsWith("/presence"))).toBe(false);

      visibility.mockReturnValue("visible");
      document.dispatchEvent(new Event("visibilitychange"));
      await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/presence"))).toBe(true));
    } finally {
      visibility.mockRestore();
    }
  });

  it("a save conflict names who saved and lets the unsaved text be copied", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    editor(envelope({ my_level: "edit", can_read_transcript: true }), {
      [`PUT /v1/notes/${NOTE}/draft`]: { status: 409, body: { code: "version_conflict" } },
      [`/v1/notes/${NOTE}/versions`]: {
        body: [
          { id: "v1", version_number: 1, parent_version_id: null, created_by: ME, created_by_display: "Sam", created_at: "2026-10-13T09:00:00Z", is_amendment: false, amendment_type: null, amendment_reason: null },
          { id: "v2", version_number: 2, parent_version_id: "v1", created_by: ANNA, created_by_display: "Anna", created_at: "2026-10-13T09:05:00Z", is_amendment: false, amendment_type: null, amendment_reason: null },
        ],
      },
    });
    const title = await screen.findByLabelText("Note title");
    await userEvent.type(title, " v2");
    const banner = await screen.findByText(/saved a newer version of this note/, {}, { timeout: 3000 });
    await waitFor(() => expect(banner).toHaveTextContent("Anna saved a newer version of this note."));
    await userEvent.click(screen.getByRole("button", { name: "Copy my unsaved text" }));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("Acme kickoff v2"));
    expect(screen.getByRole("button", { name: "Reload latest" })).toBeInTheDocument();
  });

  it("opens the comments panel on a section", async () => {
    editor(envelope());
    await userEvent.click(await screen.findByRole("button", { name: /comment on decisions/i }));
    const aside = await screen.findByRole("complementary", { name: "Comments" });
    expect(aside).toHaveTextContent(/on decisions/i);
  });
});

// ── notes list scopes ─────────────────────────────────────────────────

const HITS = {
  hits: [
    {
      note_id: NOTE,
      code: "NOTE-1",
      title: "Acme kickoff",
      status: "draft",
      template_id: "t",
      primary_author_id: ANNA,
      co_author_ids: [],
      snippet: "",
      updated_at: new Date().toISOString(),
      visibility: "workspace",
      my_level: "comment",
      collaborator_count: 2,
    },
  ],
  next_cursor: null,
};

function home(path = "/") {
  return render(
    <ToasterProvider>
      <MemoryRouter initialEntries={[path]}>
        <SpacesProvider>
          <Routes>
            <Route path="/" element={<NotesPage />} />
          </Routes>
        </SpacesProvider>
      </MemoryRouter>
    </ToasterProvider>,
  );
}

describe("notes list — scope", () => {
  it("All / My notes / Shared with me (`?scope=`) sends the scope, and each row says the level", async () => {
    const calls = server({ "/v1/notes/search": { body: HITS }, "/v1/spaces": { body: { spaces: [] } } });
    const { unmount } = home();
    expect(await screen.findByText("Can comment")).toBeInTheDocument();
    // Not the manager: no access menu, no trash.
    expect(screen.queryByRole("button", { name: /visible to everyone in the workspace/i })).toBeNull();
    expect(calls.filter((c) => c.path === "/v1/notes/search").every((c) => !c.query.has("scope"))).toBe(true);
    unmount();
    const shared = home("/?scope=shared_with_me");
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/v1/notes/search" && c.query.get("scope") === "shared_with_me")).toBe(true),
    );
    shared.unmount();
    home("/?scope=mine");
    await waitFor(() => expect(calls.some((c) => c.query.get("scope") === "mine")).toBe(true));
  });

  it("a guest sees only Shared with me, and nothing to start", async () => {
    signedIn("guest");
    const calls = server({ "/v1/notes/search": { body: HITS }, "/v1/spaces": { body: { spaces: [] } } });
    home();
    await screen.findByText("Acme kickoff");
    expect(screen.getByText("Guest · can comment")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: /show notes/i })).toBeNull();
    expect(screen.queryByRole("group", { name: /start a note/i })).toBeNull();
    expect(calls.filter((c) => c.path === "/v1/notes/search").every((c) => c.query.get("scope") === "shared_with_me")).toBe(true);
  });
});

// ── guest shell ───────────────────────────────────────────────────────

describe("guest shell", () => {
  it("names a guest workspace 'Guest in …'", () => {
    expect(workspaceLabel({ kind: "team", name: "Acme Inc", role: "guest" })).toBe("Guest in Acme Inc");
    expect(workspaceLabel({ kind: "team", name: "Acme Inc", role: "member" })).toBe("Acme Inc");
  });

  it("the switcher shows the guest workspace with a badge", async () => {
    signedIn("guest");
    server({
      "/tenants": {
        body: {
          items: [
            { id: PERSONAL, name: "Sam", display_name: "", slug: null, status: "active", is_active: false, logo_url: "", my_role: "owner", kind: "personal" },
            { id: TEAM, name: "Acme Inc", display_name: "Acme Inc", slug: null, status: "active", is_active: true, logo_url: "", my_role: "guest", kind: "team" },
          ],
        },
      },
    });
    render(
      <ToasterProvider>
        <MemoryRouter>
          <WorkspaceMenu collapsed={false} />
        </MemoryRouter>
      </ToasterProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /guest in acme inc/i }));
    const row = await screen.findByRole("menuitemradio", { name: /guest in acme inc/i });
    expect(within(row).getByText("Guest")).toHaveClass("guest-badge");
  });

  it("a guest's Settings is the Account group only", () => {
    signedIn("guest");
    render(
      <MemoryRouter initialEntries={["/settings/account"]}>
        <Routes>
          <Route path="/settings/*" element={<SettingsLayout />} />
        </Routes>
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(within(nav).getByRole("link", { name: "Profile" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Security" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Members" })).toBeNull();
    expect(within(nav).queryByText("Workspace")).toBeNull();
  });

  it("hides New meeting and Spaces for a guest, keeps them for a member", async () => {
    server({ "/v1/spaces": { body: { spaces: [] } } });
    signedIn("guest");
    const { unmount } = render(
      <ToasterProvider>
        <MemoryRouter>
          <SpacesProvider>
            <AppShell />
          </SpacesProvider>
        </MemoryRouter>
      </ToasterProvider>,
    );
    expect(screen.queryByRole("button", { name: /new meeting/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /more ways to start/i })).toBeNull();
    unmount();

    signedIn("member");
    render(
      <ToasterProvider>
        <MemoryRouter>
          <SpacesProvider>
            <AppShell />
          </SpacesProvider>
        </MemoryRouter>
      </ToasterProvider>,
    );
    expect(screen.getByRole("button", { name: /new meeting/i })).toBeInTheDocument();
  });
});

// ── small rules ───────────────────────────────────────────────────────

describe("levels and presence copy", () => {
  it("maps levels to capabilities; an older server keeps everything", () => {
    expect([canEditNote("edit"), canEditNote("comment"), canEditNote(undefined)]).toEqual([true, false, true]);
    expect([canManageNote("edit"), canManageNote("manage"), canManageNote(undefined)]).toEqual([false, true, true]);
    expect([canCommentNote("comment"), canCommentNote("view"), canCommentNote(undefined)]).toEqual([true, false, false]);
    expect(readOnlyStrip("edit")).toBeNull();
  });

  it("the list chip says the level, and Guest for a guest", () => {
    expect(levelBadgeLabel("comment")).toBe("Can comment");
    expect(levelBadgeLabel("comment", true)).toBe("Guest · can comment");
    expect(levelBadgeLabel("view", true)).toBe("Guest · can view");
  });

  it("says who is viewing", () => {
    const a = { sub: "a", display_name: "Anna" };
    const t = { sub: "t", display_name: "Tom" };
    expect(presenceLabel([a])).toBe("Anna is viewing");
    expect(presenceLabel([a, t])).toBe("Anna and Tom are viewing");
    expect(presenceLabel([a, t, { sub: "j", display_name: "Jo" }])).toBe("Anna and 2 others are viewing");
  });
});
