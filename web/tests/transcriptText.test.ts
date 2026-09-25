import { describe, expect, it } from "vitest";
import type { TranscriptTurn } from "../src/api/types";
import { isOtherLanguage, promptEchoLine, transcriptCopyText } from "../src/lib/transcriptText";

function turn(over: Partial<TranscriptTurn> = {}): TranscriptTurn {
  return { speaker: "SPEAKER_1", name: "Anna", start_ms: 0, end_ms: 1000, paragraphs: ["Hello."], ...over };
}

const nameOf = (t: TranscriptTurn) => t.name ?? "Unknown";

describe("the transcript as text (Sprint I2)", () => {
  const turns = [
    turn(),
    turn({ speaker: "SPEAKER_2", name: "Olena", start_ms: 1000, paragraphs: ["Привіт усім."], language: "uk" }),
    turn({ start_ms: 2000, paragraphs: ["Let's start.", "Agenda first."] }),
  ];

  it("leaves out turns in another language by default", () => {
    expect(transcriptCopyText(turns, nameOf, { diarized: true, includeOtherLanguages: false })).toBe(
      "Anna: Hello.\n\nAnna: Let's start.\nAgenda first.",
    );
  });

  it("includes them when asked", () => {
    expect(transcriptCopyText(turns, nameOf, { diarized: true, includeOtherLanguages: true })).toBe(
      "Anna: Hello.\n\nOlena: Привіт усім.\n\nAnna: Let's start.\nAgenda first.",
    );
  });

  it("drops the names when speakers were not told apart", () => {
    expect(transcriptCopyText(turns, nameOf, { diarized: false, includeOtherLanguages: false })).toBe(
      "Hello.\n\nLet's start.\nAgenda first.",
    );
  });

  it("treats null and empty language as the recording's own", () => {
    expect(isOtherLanguage({ language: null })).toBe(false);
    expect(isOtherLanguage({ language: "" })).toBe(false);
    expect(isOtherLanguage({})).toBe(false);
    expect(isOtherLanguage({ language: "uk" })).toBe(true);
  });
});

describe("the prompt-echo line", () => {
  it("is nothing when nothing was removed", () => {
    expect(promptEchoLine(undefined)).toBeNull();
    expect(
      promptEchoLine({ prompt_echo: [], prompt_echo_segments_dropped: 0, other_language_chunks: 0 }),
    ).toBeNull();
  });

  it("sums the words and lists the places in time order", () => {
    expect(
      promptEchoLine({
        prompt_echo: [
          { start_ms: 100_000, end_ms: 104_000, words: 5 },
          { start_ms: 3_000, end_ms: 6_000, words: 7 },
        ],
        prompt_echo_segments_dropped: 2,
        other_language_chunks: 0,
      }),
    ).toBe("12 words removed as prompt echo at 00:03, 01:40");
  });

  it("says 'word' for one", () => {
    expect(
      promptEchoLine({
        prompt_echo: [{ start_ms: 0, end_ms: 500, words: 1 }],
        prompt_echo_segments_dropped: 1,
        other_language_chunks: 0,
      }),
    ).toBe("1 word removed as prompt echo at 00:00");
  });
});
