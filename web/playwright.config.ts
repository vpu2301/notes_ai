import { defineConfig, devices } from "@playwright/test";

/**
 * The browser suite. Separate from Vitest on purpose — these need a real
 * auth-service, a real Mailpit and a real microphone permission, and none
 * of that belongs in a jsdom unit run.
 *
 * The stack it expects (`make web-e2e` brings it up):
 *
 *   auth-service   MDX_IDP_MODE=native, SMTP pointed at Mailpit
 *   mailpit        :8025 — the only way a test can read a sign-in code
 *   note/asr       the recorder path needs both
 *
 * `webServer` builds and previews rather than running `vite dev`: 5173 is
 * the origin every backend's CORS allow-list names, and the preview server
 * serves the same bundle CI ships. `reuseExistingServer` keeps a developer
 * who already has `npm run dev` open from fighting the runner for the port.
 */
export default defineConfig({
  testDir: "./e2e",
  // The first-use test waits on a real transcription. Generous, and the
  // individual waits inside it are tighter, so a hang still fails fast at
  // the step that hung rather than here.
  timeout: 5 * 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  // Every spec signs up a fresh identity against one shared database, and a
  // retry that re-runs a signup is a second account rather than a second
  // attempt. Retries would hide flakiness in exactly the flow being proved.
  retries: 0,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: process.env.WEB_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    // The recorder asks for it, and a permission dialog is not something a
    // test can click. Granting is honest here: the stream is fake.
    permissions: ["microphone"],
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          args: [
            // A synthetic audio device, so `getUserMedia({audio:true})`
            // resolves with a real MediaStream carrying a real tone —
            // rather than a monkey-patched `navigator.mediaDevices`, which
            // would prove the test's stub works and nothing about
            // MediaRecorder.
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
          ],
        },
      },
    },
  ],
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
