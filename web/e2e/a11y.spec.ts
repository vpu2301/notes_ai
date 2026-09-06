import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { freshEmail, signInWithCode } from "./helpers";

/**
 * WEB-1b §5 — axe on the sign-up path: `/login`, `/welcome`, and the empty
 * workspace. No critical issues.
 *
 * Scoped to `critical` deliberately. A gate that fails on every `moderate`
 * contrast note gets muted within a sprint, and a muted gate protects
 * nothing; a critical axe finding on a sign-in screen is somebody who
 * cannot get in at all. The serious/moderate findings are printed on
 * failure so they are visible without blocking, and the codes are listed
 * rather than summarised so a failure names the element.
 */

/** Fails on `critical` only, but reports everything it saw. */
async function scan(page: import("@playwright/test").Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const critical = results.violations.filter((v) => v.impact === "critical");
  const rest = results.violations.filter((v) => v.impact !== "critical");
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

  // The code step is a different screen inside the same route, and the
  // boxed input is the part most likely to fail — six inputs that are one
  // control need names axe can resolve.
  await page.getByLabel(/email/i).fill(email);
  await page.getByRole("button", { name: /email me a code/i }).click();
  await expect(page.getByText(/check your email/i)).toBeVisible();
  await scan(page, "/login (code)");

  await page.goto("/login/password");
  await scan(page, "/login/password");

  // BE-0's screen. Its first step renders without a server call, so this
  // scan holds on the native-mode e2e stack too, where `/auth/signup` is
  // not mounted at all.
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
