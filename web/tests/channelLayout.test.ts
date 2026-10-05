import { beforeEach, describe, expect, it, vi } from "vitest";
import { submitJob, submitWithLayoutFallback, type SubmitJobParams } from "../src/api/asr";
import { ApiError } from "../src/api/http";
import { chooseLayout } from "../src/lib/useRecorder";

/** "Me" / "Them": the recorder's fallback rule, the upload fields, and the once-only mono retry on `channel_layout_mismatch`. */

const http = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../src/api/http", async (orig) => ({
  ...(await orig<typeof import("../src/api/http")>()),
  api: http.api,
}));

const base: SubmitJobParams = {
  audio: new Blob(["x"], { type: "audio/webm" }),
  filename: "m.webm",
  language: "auto",
  diarize: true,
};

function sentForm(): FormData {
  const opts = http.api.mock.calls[0]![2] as { form: FormData };
  return opts.form;
}

beforeEach(() => {
  http.api.mockReset().mockResolvedValue({ id: "job-1", status: "queued" });
});

describe("chooseLayout", () => {
  it("is mono, with nothing to report, when tab audio was never asked for", () => {
    expect(chooseLayout(false, false)).toEqual({ layout: "mono", fellBack: false });
    // A stray system track without the option is not recorded either.
    expect(chooseLayout(false, true)).toEqual({ layout: "mono", fellBack: false });
  });

  it("is mic_system when tab audio was asked for and offered", () => {
    expect(chooseLayout(true, true)).toEqual({ layout: "mic_system", fellBack: false });
  });

  it("falls back to mono, and says so, when tab audio was asked for but not offered", () => {
    expect(chooseLayout(true, false)).toEqual({ layout: "mono", fellBack: true });
  });
});

describe("submitJob channel fields", () => {
  it("sends neither field by default", async () => {
    await submitJob(base);
    const form = sentForm();
    expect(form.has("channel_layout")).toBe(false);
    expect(form.has("local_speaker_name")).toBe(false);
  });

  it("does not declare mono — the server's default", async () => {
    await submitJob({ ...base, channelLayout: "mono" });
    expect(sentForm().has("channel_layout")).toBe(false);
  });

  it("declares mic_system and names the author's channel", async () => {
    await submitJob({ ...base, channelLayout: "mic_system", localSpeakerName: "  Ada Lovelace " });
    const form = sentForm();
    expect(form.get("channel_layout")).toBe("mic_system");
    expect(form.get("local_speaker_name")).toBe("Ada Lovelace");
  });

  it("drops an empty name", async () => {
    await submitJob({ ...base, channelLayout: "mic_system", localSpeakerName: "   " });
    expect(sentForm().has("local_speaker_name")).toBe(false);
  });
});

describe("submitWithLayoutFallback", () => {
  const mismatch = () =>
    new ApiError(422, { code: "channel_layout_mismatch", detail: "not 2 channels" });
  const job = { id: "job-2", status: "queued" };

  it("posts once when the server accepts the layout", async () => {
    const send = vi.fn().mockResolvedValue(job);
    const res = await submitWithLayoutFallback(send, { ...base, channelLayout: "mic_system" });
    expect(res).toEqual({ job, fellBackToMono: false });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("re-posts the same file as mono, once, on channel_layout_mismatch", async () => {
    const send = vi.fn().mockRejectedValueOnce(mismatch()).mockResolvedValueOnce(job);
    const res = await submitWithLayoutFallback(send, {
      ...base,
      channelLayout: "mic_system",
      localSpeakerName: "Ada",
    });
    expect(res).toEqual({ job, fellBackToMono: true });
    expect(send).toHaveBeenCalledTimes(2);
    const retry = send.mock.calls[1]![0] as SubmitJobParams;
    expect(retry.audio).toBe(base.audio);
    expect(retry.channelLayout).toBeUndefined();
    expect(retry.localSpeakerName).toBeUndefined();
    expect(retry.language).toBe("auto");
  });

  it("does not retry a second mismatch", async () => {
    const send = vi.fn().mockRejectedValue(mismatch());
    await expect(
      submitWithLayoutFallback(send, { ...base, channelLayout: "mic_system" }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("does not retry a mono upload, or any other error", async () => {
    const mono = vi.fn().mockRejectedValue(mismatch());
    await expect(submitWithLayoutFallback(mono, base)).rejects.toBeInstanceOf(ApiError);
    expect(mono).toHaveBeenCalledTimes(1);

    const other = vi
      .fn()
      .mockRejectedValue(new ApiError(413, { code: "audio_too_large", detail: "too big" }));
    await expect(
      submitWithLayoutFallback(other, { ...base, channelLayout: "mic_system" }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(other).toHaveBeenCalledTimes(1);
  });
});
