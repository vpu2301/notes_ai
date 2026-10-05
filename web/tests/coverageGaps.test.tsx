import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TranscriptCoverage } from "../src/api/types";
import { NotTranscribed } from "../src/components/NotTranscribed";
import { clock, gapReason, notTranscribedLine } from "../src/lib/coverageGaps";

/** The "Not transcribed" line on the Transcript tab. */

const full: TranscriptCoverage = {
  speech_ms: 120_000,
  transcribed_ms: 120_000,
  first_speech_ms: 11_000,
  first_segment_ms: 11_200,
  share: 1,
  vad: "silero",
  gaps: [],
};

const withGaps = (gaps: TranscriptCoverage["gaps"]): TranscriptCoverage => ({
  ...full,
  transcribed_ms: 76_000,
  share: 0.63,
  gaps,
});

describe("coverage gap wording", () => {
  it("names each cause in words", () => {
    expect(gapReason("no_audio")).toBe("audio started late");
    expect(gapReason("no_speech_detected")).toBe("no speech detected");
    expect(gapReason("decoder_empty")).toBe("could not be decoded");
    expect(gapReason("prompt_echo")).toBe("could not be decoded");
    expect(gapReason("unknown")).toBe("could not be decoded");
    expect(gapReason("other_language")).toBe("another language");
    // A cause a newer server invents reads as "could not be decoded".
    expect(gapReason("something_new")).toBe("could not be decoded");
  });

  it("writes mm:ss, and h:mm:ss from an hour on", () => {
    expect(clock(0)).toBe("00:00");
    expect(clock(44_900)).toBe("00:44");
    expect(clock(3_599_000)).toBe("59:59");
    expect(clock(3_661_000)).toBe("1:01:01");
  });

  it("is one line, in time order, the late start first", () => {
    const line = notTranscribedLine(
      withGaps([
        { start_ms: 69_000, end_ms: 99_000, cause: "decoder_empty" },
        { start_ms: 11_000, end_ms: 41_000, cause: "prompt_echo" },
        { start_ms: 0, end_ms: 3_000, cause: "no_audio" },
      ]),
    );
    expect(line).toBe(
      "Not transcribed: 00:00–00:03 (audio started late), 00:11–00:41 (could not be decoded), 01:09–01:39 (could not be decoded)",
    );
  });

  it("shows four ranges and counts the rest", () => {
    const gaps = Array.from({ length: 6 }, (_, i) => ({
      start_ms: i * 60_000,
      end_ms: i * 60_000 + 5_000,
      cause: "no_speech_detected" as const,
    }));
    const line = notTranscribedLine(withGaps(gaps))!;
    expect(line.endsWith(" +2 more")).toBe(true);
    expect(line.split("(no speech detected)")).toHaveLength(5);
  });

  it("says nothing for a full recording or an older result", () => {
    expect(notTranscribedLine(full)).toBeNull();
    expect(notTranscribedLine(null)).toBeNull();
    expect(notTranscribedLine(undefined)).toBeNull();
  });
});

describe("<NotTranscribed>", () => {
  it("renders the line, and a range opens the transcript at its start", () => {
    const onSeek = vi.fn();
    render(
      <NotTranscribed
        coverage={withGaps([
          { start_ms: 0, end_ms: 2_500, cause: "no_audio" },
          { start_ms: 11_000, end_ms: 44_000, cause: "prompt_echo" },
        ])}
        onSeek={onSeek}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "Not transcribed: 00:00–00:02 (audio started late), 00:11–00:44 (could not be decoded)",
    );
    // The late start is before the recording: nothing to open.
    expect(screen.queryByRole("button", { name: /audio started late/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "00:11–00:44 (could not be decoded)" }));
    expect(onSeek).toHaveBeenCalledWith(11_000);
  });

  it("renders nothing when everything was transcribed", () => {
    const { container } = render(<NotTranscribed coverage={full} onSeek={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a result without coverage", () => {
    const { container } = render(<NotTranscribed coverage={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
