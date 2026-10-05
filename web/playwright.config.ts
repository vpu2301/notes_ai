import { defineConfig, devices } from "@playwright/test";

/**
 * Browser suite; needs the `make web-e2e` stack (auth-service in native mode,
 * Mailpit on :8025 for sign-in codes, note/asr for the recorder path).
 * Builds + previews on 5173 (the CORS-allowed origin) rather than `vite dev`.
 */
export default defineConfig({
  testDir: "./e2e",
  // First-use waits on a real transcription; inner waits are tighter.
  timeout: 5 * 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  // A retried signup is a second account, not a second attempt.
  retries: 0,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: process.env.WEB_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    // The recorder asks; the stream is fake anyway.
    permissions: ["microphone"],
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          args: [
            // Real MediaStream with a tone, so MediaRecorder itself is exercised.
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
