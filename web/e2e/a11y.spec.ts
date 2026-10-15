import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { freshEmail, signInWithCode } from "./helpers";

/**
 * axe on the sign-up path. Gated on `critical` only (a gate that fails on every
 * moderate finding gets muted); lesser findings are printed, not blocking.
 */

/** Fails on `critical` only, but reports everything it saw. */
async function scan(page: import("@playwright/test").Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const critical = results.violations.filter((v) => v.impact === "critical");
  const rest = results.violations.filter((v) => v.impact !== "critical");
  if (process.env.AXE_VERBOSE) {
    for (const v of rest) for (const n of v.nodes) console.log(v.id, n.target.join(" "), n.failureSummary);
  }
  if (rest.length > 0) {
    console.log(
      `${label}: ${rest.length} non-critical axe finding(s) — ` +
        rest.map((v) => `${v.id}(${v.impact})`).join(", "),
    );
  }
  expect(
    critical,
    `${label}: ${critical.map((v) => `${v.id} on ${v.nodes[0]?.target.join(" ")}`).join("; ")}`,
  ).toEqual([]);
}

test("the sign-up path has no critical accessibility failures", async ({ page }) => {
  const email = freshEmail("axe");

  await page.goto("/login");
  await scan(page, "/login (address)");

  // The code step: six inputs that are one control need names axe can resolve.
  await page.getByLabel(/email/i).fill(email);
  await page.getByRole("button", { name: /email me a code/i }).click();
  await expect(page.getByText(/check your email/i)).toBeVisible();
  await scan(page, "/login (code)");

  await page.goto("/login/password");
  await scan(page, "/login/password");

  // The first step renders without a server call, so this holds where `/auth/signup` is not mounted.
  await page.goto("/signup");
  await scan(page, "/signup");
});

test("/welcome and the empty workspace have no critical accessibility failures", async ({
  page,
}) => {
  await signInWithCode(page, freshEmail("axe-welcome"));

  await expect(page).toHaveURL(/\/welcome$/);
  await scan(page, "/welcome");

  await page.getByRole("button", { name: /skip for now/i }).click();
  await expect(page.getByRole("region", { name: /get started/i })).toBeVisible();
  await scan(page, "/ (empty workspace)");
});

/**
 * The transcript page's speaker controls against a mocked backend. Every call to
 * the service origins is answered here; none may reach a dev database on those ports.
 */
const ORIGINS = /^http:\/\/localhost:800[0-9]\//;
const NOTE_ID = "11111111-1111-4111-8111-111111111111";
const JOB_ID = "22222222-2222-4222-8222-222222222222";
const NOW = "2026-09-19T10:00:00Z";

const TRANSCRIPT = {
  job_id: JOB_ID,
  language: "en",
  segments: [],
  speakers: ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"],
  speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Speaker 2", SPEAKER_3: "Speaker 3" },
  speaker_name_sources: { SPEAKER_1: "channel" },
  speaker_sides: { SPEAKER_1: "local", SPEAKER_2: "remote", SPEAKER_3: "remote" },
  speaker_stats: [
    { label: "SPEAKER_1", speech_ms: 300_000, share: 0.6, turns: 2 },
    { label: "SPEAKER_2", speech_ms: 190_000, share: 0.38, turns: 1 },
    { label: "SPEAKER_3", speech_ms: 8_000, share: 0.02, turns: 1 },
  ],
  result_rev: 3,
  edits: [],
  count_confidence: "low",
  name_candidates: ["Anna", "Tom Berg"],
  name_suggestions: [
    {
      label: "SPEAKER_2",
      name: "Tom Berg",
      source: "self_introduction",
      quote: "Hi Anna, Tom here from Acme",
      start_ms: 14_000,
      end_ms: 16_200,
      segment_indices: [42],
    },
  ],
  relabel_available: true,
  turns: [
    { speaker: "SPEAKER_1", name: "Anna", start_ms: 0, end_ms: 5000, paragraphs: ["Hello all."], segment_indices: [40, 41] },
    {
      speaker: "SPEAKER_2",
      name: "Speaker 2",
      start_ms: 14_000,
      end_ms: 16_200,
      paragraphs: ["Hi Anna, Tom here from Acme."],
      segment_indices: [42],
      uncertain: true,
    },
    { speaker: "SPEAKER_3", name: "Speaker 3", start_ms: 17_000, end_ms: 19_000, paragraphs: ["Yes."], segment_indices: [44] },
    { speaker: "SPEAKER_1", name: "Anna", start_ms: 20_000, end_ms: 24_000, paragraphs: ["Let's start."], segment_indices: [45] },
  ],
};

function mockBody(method: string, path: string): unknown {
  if (path === "/auth/refresh") return { access_token: "e2e-token", expires_in: 3600, token_type: "Bearer" };
  if (path === "/auth/me") {
    return {
      claims: { sub: "u-1", tid: "t-1", roles: ["owner"] },
      db_user: null,
      identity: {
        id: "u-1",
        email: "axe@example.test",
        display_name: "Axe Test",
        mfa_enabled: false,
        has_password: false,
        status: "active",
        created_at: "2025-01-01T00:00:00Z",
      },
      memberships: [{ tenant_id: "t-1", name: "Axe", kind: "personal", role: "owner", status: "active" }],
    };
  }
  if (path === `/v1/notes/${NOTE_ID}`) {
    return {
      id: NOTE_ID,
      code: "N-1",
      status: "draft",
      current_version_id: "v-1",
      current_version_number: 1,
      primary_author_id: "u-1",
      co_author_ids: [],
      title: "Weekly sync",
      created_at: NOW,
      updated_at: NOW,
      finalized_at: null,
      cancelled_at: null,
      source_job_id: JOB_ID,
      visibility: "private",
      content: { template_id: "", template_schema_version: 1, title: "Weekly sync", sections: [] },
      section_labels: [],
    };
  }
  if (path === `/asr/jobs/${JOB_ID}/result`) return TRANSCRIPT;
  if (path === `/asr/jobs/${JOB_ID}`) {
    return {
      id: JOB_ID,
      tenant_id: "t-1",
      audio_id: "a-1",
      requester_sub: "u-1",
      language: "en",
      model: "m",
      status: "complete",
      queued_at: NOW,
      error_message: null,
      error_stage: null,
      error_retryable: null,
      diarization_status: "complete",
      can_undo_rediarize: false,
    };
  }
  if (path === "/v1/spaces") return { spaces: [] };
  if (path === "/v1/notifications/unread-count") return { unread_count: 0 };
  if (path === "/v1/notifications") return { items: [], unread_count: 0, next_cursor: null };
  if (path === "/v1/calendar/connections") return { connections: [] };
  if (path === "/v1/calendar/events") return { events: [] };
  if (path === "/v1/notes/search") return { items: [], total: 0 };
  if (path.endsWith("/sharing")) return { visibility: "private", members: [], links: [] };
  return method === "GET" ? [] : {};
}

/** Inside `.transcript` every axe finding fails (AA, contrast included); the page chrome is only gated on `critical`. */
async function scanTranscript(page: import("@playwright/test").Page, label: string) {
  await scan(page, label);
  const results = await new AxeBuilder({ page })
    .include(".transcript")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations,
    `${label} (transcript): ${results.violations.map((v) => `${v.id} on ${v.nodes[0]?.target.join(" ")}`).join("; ")}`,
  ).toEqual([]);
}

async function mockBackend(page: import("@playwright/test").Page) {
  await page.route(ORIGINS, async (route) => {
    const req = route.request();
    const cors = {
      "access-control-allow-origin": "http://localhost:5173",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization, content-type, x-client-type, x-request-id",
      "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    };
    if (req.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    const path = new URL(req.url()).pathname;
    await route.fulfill({ status: 200, headers: cors, contentType: "application/json", body: JSON.stringify(mockBody(req.method(), path)) });
  });
}

test("the transcript's speaker controls have no critical accessibility failures", async ({ page }) => {
  await mockBackend(page);
  await page.goto(`/notes/${NOTE_ID}`);
  await page.getByRole("tab", { name: /transcript/i }).click();

  // The speaker controls, visible before the scan.
  const roster = page.locator(".speaker-roster");
  await expect(roster.getByText(/older method/)).toBeVisible();
  await expect(page.getByRole("group", { name: "Name suggestion for Speaker 2" }).first()).toBeVisible();
  await scanTranscript(page, "transcript (suggestion + re-label offer)");

  // The move menu, opened and driven from the keyboard alone.
  const avatar = page.locator('[data-turn-index="0"]').getByRole("button", { name: /move this turn/ });
  await avatar.focus();
  await page.keyboard.press("Enter");
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem").first()).toBeFocused();
  await scanTranscript(page, "transcript (move menu open)");
  await page.keyboard.press("Escape");
  await expect(avatar).toBeFocused();

  // A roster chip's menu, and the multi-select bar.
  await page.getByRole("button", { name: /Speaker 3 — rename or merge/ }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  await scanTranscript(page, "transcript (chip menu open)");
  await page.keyboard.press("Escape");
  await page.locator('[data-turn-index="3"]').getByRole("checkbox").check();
  await expect(page.getByRole("toolbar", { name: "Selected turns" })).toBeVisible();
  await scanTranscript(page, "transcript (turns selected)");

  // The quote goes to its turn.
  await page.getByRole("button", { name: /show this at 00:14/ }).click();
  await expect(page.locator('[data-turn-index="1"]')).toBeFocused();
  await expect(page.locator('[data-turn-index="1"]')).toHaveClass(/highlighted/);
});

test("the transcript's speaker controls hold AA contrast in the dark theme too", async ({ page }) => {
  // Light by default; dark is a remembered choice.
  await page.addInitScript(() => localStorage.setItem("notesai.theme", "dark"));
  await mockBackend(page);
  await page.goto(`/notes/${NOTE_ID}`);
  await page.getByRole("tab", { name: /transcript/i }).click();
  await expect(page.getByRole("group", { name: "Name suggestion for Speaker 2" }).first()).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await scanTranscript(page, "transcript, dark");
  await page.locator('[data-turn-index="0"]').getByRole("button", { name: /move this turn/ }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  await scanTranscript(page, "transcript, dark (move menu open)");
});

/**
 * The collaboration surfaces (work order phases 2–3) against a mocked backend: the share dialog,
 * the comments panel, the members page and the invite landing, in light and dark.
 */
const TEAM_ID = "33333333-3333-4333-8333-333333333333";
const ANNA_ID = "55555555-5555-4555-8555-555555555555";

function collabBody(method: string, path: string): unknown {
  if (path === "/auth/refresh") return { access_token: "e2e-token", expires_in: 3600, token_type: "Bearer", tenant_id: TEAM_ID };
  if (path === "/auth/me") {
    return {
      claims: { sub: "u-1", tid: TEAM_ID, roles: ["owner"] },
      db_user: null,
      identity: {
        id: "u-1",
        email: "axe@example.test",
        display_name: "Axe Test",
        mfa_enabled: false,
        has_password: false,
        status: "active",
        created_at: "2025-01-01T00:00:00Z",
      },
      memberships: [{ tenant_id: TEAM_ID, name: "Sunrise Studio", kind: "team", role: "owner", status: "active" }],
    };
  }
  if (path === `/v1/notes/${NOTE_ID}`) {
    return { ...(mockBody(method, path) as object), source_job_id: null, my_level: "manage", can_read_transcript: true };
  }
  if (path.endsWith("/sharing")) {
    return {
      note_id: NOTE_ID,
      visibility: "private",
      can_manage: true,
      can_delete: true,
      shared_with: [],
      public_link: null,
      links: [],
      my_level: "manage",
      workspace_kind: "team",
      transcript_shared: false,
      people: [
        { sub: "u-1", email: "axe@example.test", display_name: "Axe Test", level: "manage", source: "author", membership_role: "owner", can_change: false },
        { sub: ANNA_ID, email: "anna@example.test", display_name: "Anna", level: "comment", source: "collaborator", membership_role: "member", can_change: true },
      ],
      pending: [{ invitation_id: "inv-1", email_masked: "t•••@client.test", note_role: "view", expires_at: NOW }],
    };
  }
  if (path.endsWith("/comments")) {
    return {
      items: [
        {
          id: "c-1",
          author: { sub: ANNA_ID, display_name: "Anna" },
          anchor_kind: "note",
          anchor_key: null,
          anchor_present: true,
          body: "Is this final?",
          created_at: NOW,
          edited_at: null,
          resolved_at: null,
          resolved_by_display: null,
          can_edit: false,
          can_resolve: true,
          can_delete: false,
        },
      ],
    };
  }
  if (path.endsWith("/presence")) return method === "GET" ? { viewers: [] } : {};
  if (path === `/tenants/${TEAM_ID}/members`) {
    return {
      items: [
        { user_sub: "u-1", role: "owner", status: "active", email: "axe@example.test", display_name: "Axe Test", platform_role: null, created_at: NOW, updated_at: NOW },
        { user_sub: ANNA_ID, role: "member", status: "active", email: "anna@example.test", display_name: "Anna", platform_role: null, created_at: NOW, updated_at: NOW },
      ],
      seat_meter: { active: 2, limit: 3 },
    };
  }
  if (path === `/tenants/${TEAM_ID}/invitations`) {
    return {
      items: [
        { id: "inv-1", email: "tom@client.test", role: "member", status: "pending", expires_at: "2026-12-01T00:00:00Z", sent_count: 1, last_sent_at: NOW, invited_by_display: "Axe Test", created_at: NOW, delivery: "sent" },
      ],
    };
  }
  if (path === "/auth/invitations/tok") {
    return { workspace_name: "Sunrise Studio", inviter_display: "Anna", role: "member", email_masked: "t•••@client.test", expires_at: "2026-12-01T00:00:00Z", note_title: null };
  }
  if (path === "/auth/invitations") return { items: [] };
  return mockBody(method, path);
}

async function mockCollabBackend(page: import("@playwright/test").Page, signedIn = true) {
  await page.route(ORIGINS, async (route) => {
    const req = route.request();
    const cors = {
      "access-control-allow-origin": "http://localhost:5173",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization, content-type, x-client-type, x-request-id",
      "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    };
    if (req.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    const path = new URL(req.url()).pathname;
    if (!signedIn && path === "/auth/refresh") {
      await route.fulfill({ status: 401, headers: cors, contentType: "application/json", body: JSON.stringify({ code: "no_refresh_token" }) });
      return;
    }
    await route.fulfill({ status: 200, headers: cors, contentType: "application/json", body: JSON.stringify(collabBody(req.method(), path)) });
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`share dialog and comments panel: keyboard path and no critical failures (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("notesai.theme", t), theme);
    await mockCollabBackend(page);
    await page.goto(`/notes/${NOTE_ID}`);

    await page.getByRole("button", { name: /more actions/i }).click();
    await page.getByRole("menuitem", { name: /share…/i }).click();
    const dialog = page.getByRole("dialog", { name: "Share note" });
    await expect(dialog.getByLabel("Who has access")).toBeVisible();
    await scan(page, `share dialog (${theme})`);

    // Chips → role → message → Share, by Tab alone.
    const box = dialog.getByLabel("Invite people");
    await box.focus();
    await page.keyboard.type("tom@client.test ");
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("button", { name: "Role", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dialog.getByLabel("Invitation message")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("button", { name: "Share", exact: true })).toBeFocused();
    await scan(page, `share dialog, composing (${theme})`);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    await page.getByRole("button", { name: /^comments/i }).click();
    const panel = page.getByRole("complementary", { name: "Comments" });
    await expect(panel.getByText("Is this final?")).toBeVisible();
    await scan(page, `comments panel (${theme})`);
    await panel.getByLabel("Comment", { exact: true }).focus();
    await page.keyboard.type("Yes, final.");
    await expect(panel.getByRole("button", { name: "Comment", exact: true })).toBeEnabled();
  });

  test(`members page and invite landing have no critical failures (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("notesai.theme", t), theme);
    await mockCollabBackend(page);
    await page.goto("/settings/members");
    await expect(page.getByLabel("Pending invitations")).toBeVisible();
    await expect(page.getByRole("meter", { name: "Seats used" })).toBeVisible();
    await scan(page, `members page (${theme})`);

    // The invite form by keyboard: address, role, Invite.
    const email = page.getByRole("textbox", { name: "Email", exact: true });
    await email.focus();
    await page.keyboard.type("jo@client.test ");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Role", exact: true })).toBeFocused();
    await scan(page, `members page, composing (${theme})`);
  });

  test(`invite landing, signed out, has no critical failures (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("notesai.theme", t), theme);
    await mockCollabBackend(page, false);
    await page.goto("/invite/tok");
    await expect(page.getByRole("button", { name: /continue with/i })).toBeVisible();
    await scan(page, `invite landing (${theme})`);
  });
}
