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
