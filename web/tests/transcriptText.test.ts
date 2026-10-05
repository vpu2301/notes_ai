import { describe, expect, it } from "vitest";
import type { TranscriptTurn } from "../src/api/types";
import {
  isOtherLanguage,
  markerLine,
  markersBefore,
  promptEchoLine,
  transcriptCopyText,
} from "../src/lib/transcriptText";

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

describe("non-speech markers (Sprint TQ2)", () => {
  const noise = [
    { start_ms: 12_000, end_ms: 41_000, kind: "music" },
    { start_ms: 61_000, end_ms: 70_000, kind: "silence" },
    { start_ms: 90_000, end_ms: 96_000, kind: "noise" },
  ];

  it("names the three kinds in the language that was spoken", () => {
    expect(noise.map((n) => markerLine(n, "de"))).toMatchInlineSnapshot(`
      [
        "[Musik 00:12–00:41]",
        "[Stille 01:01–01:10]",
        "[Geräusch 01:30–01:36]",
      ]
    `);
    expect(noise.map((n) => markerLine(n, "en"))).toMatchInlineSnapshot(`
      [
        "[Music 00:12–00:41]",
        "[Silence 01:01–01:10]",
        "[Noise 01:30–01:36]",
      ]
    `);
    expect(noise.map((n) => markerLine(n, "uk"))).toMatchInlineSnapshot(`
      [
        "[Музика 00:12–00:41]",
        "[Тиша 01:01–01:10]",
        "[Шум 01:30–01:36]",
      ]
    `);
  });

  it("renders a kind it does not know as noise", () => {
    expect(markerLine({ start_ms: 0, end_ms: 5000, kind: "applause" }, "en")).toBe("[Noise 00:00–00:05]");
  });

  it("places markers between turns without making them turns", () => {
    const turns = [{ start_ms: 0 }, { start_ms: 50_000 }, { start_ms: 80_000 }];
    expect(markersBefore(noise, turns, 0)).toEqual([]);
    expect(markersBefore(noise, turns, 1)).toEqual([noise[0]]);
    expect(markersBefore(noise, turns, 2)).toEqual([noise[1]]);
    expect(markersBefore(noise, turns, 3)).toEqual([noise[2]]);
  });

  it("stays out of a copy unless asked for", () => {
    const turns = [turn(), turn({ start_ms: 50_000, paragraphs: ["Back again."] })];
    expect(transcriptCopyText(turns, nameOf, { diarized: true, includeOtherLanguages: false })).toBe(
      "Anna: Hello.\n\nAnna: Back again.",
    );
    expect(
      transcriptCopyText(turns, nameOf, {
        diarized: true,
        includeOtherLanguages: false,
        markers: { noise: noise.slice(0, 1), language: "en" },
      }),
    ).toBe("Anna: Hello.\n\n[Music 00:12–00:41]\n\nAnna: Back again.");
  });
});
