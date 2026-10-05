import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AsrJob, NameSuggestion, TranscriptResult } from "../src/api/types";
import { SpeakerRoster } from "../src/components/SpeakerRoster";
import { ToasterProvider } from "../src/components/Toaster";
import { copyNodes, copyText, movedAnnouncement } from "../src/i18n/speakers";
import { TranscriptView, turnOfSuggestion } from "../src/pages/NoteEditorPage";

const asr = vi.hoisted(() => ({
  getResult: vi.fn(),
  getJob: vi.fn(),
  reassignTurns: vi.fn(),
  setSpeakerNames: vi.fn(),
  undoSpeakerEdit: vi.fn(),
  mergeSpeakers: vi.fn(),
  rediarize: vi.fn(),
  undoRediarize: vi.fn(),
  resetSpeakerEdits: vi.fn(),
  dismissNameSuggestion: vi.fn(),
}));
vi.mock("../src/api/asr", async (orig) => ({ ...(await orig<typeof import("../src/api/asr")>()), ...asr }));

function job(over: Partial<AsrJob> = {}): AsrJob {
  return {
    id: "job-1",
    tenant_id: "t",
    audio_id: "a",
    requester_sub: "u",
    language: "auto",
    model: "m",
    status: "complete",
    queued_at: "2026-09-19T10:00:00Z",
    error_message: null,
    error_stage: null,
    error_retryable: null,
    diarization_status: null,
    ...over,
  };
}

const TOM: NameSuggestion = {
  label: "SPEAKER_2",
  name: "Tom Berg",
  source: "self_introduction",
  quote: "Hi Anna, Tom here from Acme",
  start_ms: 14_000,
  end_ms: 16_200,
  segment_indices: [42],
};

/** Anna, Speaker 2 (who introduces himself), Anna again. */
function result(over: Partial<TranscriptResult> = {}): TranscriptResult {
  return {
    job_id: "job-1",
    language: "en",
    segments: [],
    speakers: ["SPEAKER_1", "SPEAKER_2"],
    speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Speaker 2" },
    speaker_name_sources: { SPEAKER_1: "typed" },
    speaker_stats: [
      { label: "SPEAKER_1", speech_ms: 300_000, share: 0.6, turns: 2 },
      { label: "SPEAKER_2", speech_ms: 200_000, share: 0.4, turns: 1 },
    ],
    result_rev: 3,
    edits: [],
    turns: [
      { speaker: "SPEAKER_1", name: "Anna", start_ms: 0, end_ms: 5000, paragraphs: ["Hello all."], segment_indices: [40, 41] },
      {
        speaker: "SPEAKER_2",
        name: "Speaker 2",
        start_ms: 14_000,
        end_ms: 16_200,
        paragraphs: ["Hi Anna, Tom here from Acme."],
        segment_indices: [42, 43],
      },
      { speaker: "SPEAKER_1", name: "Anna", start_ms: 17_000, end_ms: 20_000, paragraphs: ["Let's start."], segment_indices: [45] },
    ],
    ...over,
  };
}

async function renderView() {
  render(
    <ToasterProvider>
      <TranscriptView jobId="job-1" />
    </ToasterProvider>,
  );
  await screen.findByText("Hello all.");
  await waitFor(() => expect(asr.getJob).toHaveBeenCalled());
}

function turnOf(text: string): HTMLElement {
  return screen.getByText(text).closest(".turn") as HTMLElement;
}

/** What the live region said last. */
function announced(): string {
  return screen.getByRole("status", { name: copyText("announcementsRegion") }).textContent ?? "";
}

/** The roster's chip (the one away from the turn). */
function rosterChip(): HTMLElement {
  const chips = screen.getAllByRole("group", { name: "Name suggestion for Speaker 2" });
  const chip = chips.find((c) => !c.classList.contains("inline"));
  if (!chip) throw new Error("no roster chip");
  return chip;
}

beforeEach(() => {
  sessionStorage.clear();
  asr.getResult.mockReset().mockResolvedValue(result({ name_suggestions: [TOM] }));
  asr.getJob.mockReset().mockResolvedValue(job());
  asr.setSpeakerNames.mockReset().mockResolvedValue({
    job_id: "job-1",
    speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Tom Berg" },
  });
  asr.dismissNameSuggestion.mockReset().mockResolvedValue(undefined);
  asr.rediarize.mockReset().mockResolvedValue({ job_id: "job-1", diarization_status: "queued", diarization_rev: 2 });
  asr.reassignTurns.mockReset();
  asr.mergeSpeakers.mockReset();
  asr.undoSpeakerEdit.mockReset().mockResolvedValue(undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  // jsdom has no scrollIntoView; one test installs a spy.
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

describe("copy", () => {
  it("fills placeholders without concatenating", () => {
    expect(copyText("suggestionAcceptLabel", { name: "Tom Berg", speaker: "Speaker 2" })).toBe("Accept Tom Berg for Speaker 2");
    expect(movedAnnouncement(1)).toBe("Moved 1 turn");
    expect(movedAnnouncement(3)).toBe("Moved 3 turns");
    render(<p data-testid="p">{copyNodes("suggestionLead", { name: <strong>Anna</strong> })}</p>);
    expect(screen.getByTestId("p").innerHTML).toBe("Probably <strong>Anna</strong>");
  });

  it("finds the turn a quote sits in by its first segment", () => {
    const turns = result().turns!;
    expect(turnOfSuggestion(turns, TOM)).toBe(1);
    expect(turnOfSuggestion(turns, { ...TOM, segment_indices: [99] })).toBe(-1);
    expect(turnOfSuggestion(turns, { ...TOM, segment_indices: [] })).toBe(-1);
  });
});

describe("name suggestions", () => {
  it("renders nothing when the server sends no suggestions and no re-label offer", async () => {
    asr.getResult.mockResolvedValue(result());
    await renderView();
    expect(screen.queryByText(/Probably/)).toBeNull();
    expect(screen.queryByRole("group", { name: /Name suggestion/ })).toBeNull();
    expect(screen.queryByText(/older method/)).toBeNull();
    expect(screen.queryByText(/suggested/)).toBeNull();
  });

  it("shows the evidence before anyone accepts — in the roster and at the turn", async () => {
    await renderView();
    const chip = rosterChip();
    expect(within(chip).getByText("Tom Berg").tagName).toBe("STRONG");
    expect(chip).toHaveTextContent("Probably Tom Berg — “Hi Anna, Tom here from Acme” · 00:14");
    expect(within(chip).getByRole("button", { name: "Accept Tom Berg for Speaker 2" })).toBeEnabled();
    expect(within(chip).getByRole("button", { name: "Dismiss suggestion" })).toBeEnabled();

    // The same suggestion sits under the turn that holds the quote.
    const inline = within(turnOf("Hi Anna, Tom here from Acme.")).getByRole("group", { name: "Name suggestion for Speaker 2" });
    expect(inline).toHaveTextContent("Hi Anna, Tom here from Acme");
    expect(within(turnOf("Hello all.")).queryByRole("group", { name: /Name suggestion/ })).toBeNull();
  });

  it("hides a suggestion for a speaker someone already named", async () => {
    asr.getResult.mockResolvedValue(
      result({ name_suggestions: [TOM], speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Olena" } }),
    );
    await renderView();
    expect(screen.queryByRole("group", { name: /Name suggestion/ })).toBeNull();
  });

  it("accepts with every other name kept and the source 'suggestion', then marks the name", async () => {
    await renderView();
    fireEvent.click(within(rosterChip()).getByRole("button", { name: "Accept Tom Berg for Speaker 2" }));
    await waitFor(() =>
      expect(asr.setSpeakerNames).toHaveBeenCalledWith(
        "job-1",
        { SPEAKER_1: "Anna", SPEAKER_2: "Tom Berg" },
        { SPEAKER_2: "suggestion" },
      ),
    );
    expect(await screen.findByRole("button", { name: "Tom Berg (suggested) — rename or merge" })).toBeInTheDocument();
    expect(screen.getByText("· suggested")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Name suggestion/ })).toBeNull();
    expect(screen.getByText("Speaker 2 is now Tom Berg")).toBeInTheDocument();
    expect(announced()).toBe("Named Tom Berg");
  });

  it("undoes an accept by putting the previous names back", async () => {
    await renderView();
    fireEvent.click(within(rosterChip()).getByRole("button", { name: /^Accept/ }));
    await screen.findByText("Speaker 2 is now Tom Berg");
    asr.setSpeakerNames.mockResolvedValue({ job_id: "job-1", speaker_names: { SPEAKER_1: "Anna" } });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(asr.setSpeakerNames).toHaveBeenLastCalledWith("job-1", { SPEAKER_1: "Anna" }));
    await waitFor(() => expect(screen.queryByText("· suggested")).toBeNull());
    expect(screen.getByRole("button", { name: "Speaker 2 — rename or merge" })).toBeInTheDocument();
    // Back to unnamed, so the suggestion is worth offering again.
    expect(rosterChip()).toBeInTheDocument();
    expect(announced()).toBe("Undone");
  });

  it("drops the marker once the person edits the name", async () => {
    await renderView();
    fireEvent.click(within(rosterChip()).getByRole("button", { name: /^Accept/ }));
    await screen.findByText("· suggested");
    asr.setSpeakerNames.mockResolvedValue({ job_id: "job-1", speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Tom B." } });
    fireEvent.click(within(turnOf("Hi Anna, Tom here from Acme.")).getByRole("button", { name: "Tom Berg" }));
    const input = screen.getByRole("textbox", { name: "Speaker name" });
    fireEvent.change(input, { target: { value: "Tom B." } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(asr.setSpeakerNames).toHaveBeenLastCalledWith("job-1", expect.anything(), { SPEAKER_2: "typed" }));
    await waitFor(() => expect(screen.queryByText("· suggested")).toBeNull());
  });

  it("dismisses with the label and name, and the chip goes", async () => {
    await renderView();
    fireEvent.click(within(rosterChip()).getByRole("button", { name: "Dismiss suggestion" }));
    expect(asr.dismissNameSuggestion).toHaveBeenCalledWith("job-1", "SPEAKER_2", "Tom Berg");
    expect(screen.queryByRole("group", { name: /Name suggestion/ })).toBeNull();
    expect(asr.setSpeakerNames).not.toHaveBeenCalled();
  });

  it("brings a suggestion back when the dismiss fails", async () => {
    asr.dismissNameSuggestion.mockRejectedValue(new Error("offline"));
    await renderView();
    fireEvent.click(within(rosterChip()).getByRole("button", { name: "Dismiss suggestion" }));
    expect(await screen.findByText(/Couldn't dismiss the suggestion/)).toBeInTheDocument();
    expect(rosterChip()).toBeInTheDocument();
  });

  it("scrolls to the quoted turn and highlights it for two seconds", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    await renderView();
    vi.useFakeTimers();
    fireEvent.click(within(rosterChip()).getByRole("button", { name: /“Hi Anna, Tom here from Acme” — show this at 00:14/ }));
    const turn = document.querySelector<HTMLElement>('[data-turn-index="1"]')!;
    expect(turn).toBe(turnOf("Hi Anna, Tom here from Acme."));
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll.mock.contexts[0]).toBe(turn);
    expect(turn).toHaveClass("highlighted");
    expect(turn).toHaveFocus();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(turn).toHaveClass("highlighted");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(turn).not.toHaveClass("highlighted");
  });
});

describe("the re-label offer", () => {
  it("re-labels with the diarizer choosing the count", async () => {
    asr.getResult.mockResolvedValue(result({ relabel_available: true }));
    await renderView();
    const banner = screen.getByRole("region", { name: "Re-label" });
    expect(banner).toHaveTextContent(
      "Speakers were detected with an older method. Re-label? Your speaker names are kept where possible.",
    );
    fireEvent.click(within(banner).getByRole("button", { name: "Re-label" }));
    await waitFor(() => expect(asr.rediarize).toHaveBeenCalledWith("job-1", null));
    expect(await screen.findByText(/Re-labelling speakers/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Re-label" })).toBeNull();
  });

  it("is absent when the field is false or missing", async () => {
    asr.getResult.mockResolvedValue(result({ relabel_available: false }));
    await renderView();
    expect(screen.queryByText(/older method/)).toBeNull();
  });

  it("is offered on a transcript that was never told apart", async () => {
    asr.getResult.mockResolvedValue(
      result({
        speakers: [],
        speaker_names: {},
        relabel_available: true,
        turns: [{ speaker: null, name: null, start_ms: 0, end_ms: 5000, paragraphs: ["Hello all."] }],
      }),
    );
    await renderView();
    expect(screen.getByText(/older method/)).toBeInTheDocument();
    expect(screen.getByText("Speakers were not told apart in this recording.")).toBeInTheDocument();
    expect(screen.queryByText("Wrong number of speakers?")).toBeNull();
  });

  it("'Not now' puts it away for the session", () => {
    asr.getJob.mockResolvedValue(job());
    render(
      <SpeakerRoster
        jobId="job-1"
        speakers={["SPEAKER_1", "SPEAKER_2"]}
        names={{}}
        stats={[]}
        busy={false}
        undo={null}
        countConfidence="low"
        relabelAvailable
        onRename={vi.fn()}
        onMerge={vi.fn()}
      />,
    );
    // One question at a time: the offer outranks the count question.
    expect(screen.queryByText(/not sure how many people spoke/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByText(/older method/)).toBeNull();
    expect(sessionStorage.getItem("relabel-later:job-1")).toBe("1");
    expect(screen.getByText(/not sure how many people spoke/)).toBeInTheDocument();
  });
});

describe("announcements", () => {
  it("says Merged after a merge", async () => {
    asr.mergeSpeakers.mockResolvedValue({
      job_id: "job-1",
      edit_id: "e1",
      speakers: ["SPEAKER_1"],
      speaker_names: { SPEAKER_1: "Anna" },
      speaker_stats: [],
    });
    asr.getResult.mockResolvedValue(result());
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: "Speaker 2 — rename or merge" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Merge into Anna" }));
    await waitFor(() => expect(announced()).toBe("Merged"));
  });

  it("says how many turns moved", async () => {
    asr.getResult.mockResolvedValue(result());
    asr.reassignTurns.mockResolvedValue({
      job_id: "job-1",
      edit_id: "e2",
      speakers: ["SPEAKER_1", "SPEAKER_2"],
      speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Speaker 2" },
      speaker_stats: [],
      created_label: null,
    });
    await renderView();
    fireEvent.click(within(turnOf("Hello all.")).getByRole("checkbox"));
    fireEvent.click(within(turnOf("Let's start.")).getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Move 2 turns to" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Speaker 2" }));
    await waitFor(() => expect(announced()).toBe("Moved 2 turns"));
  });

  it("says when re-labelling finished", async () => {
    asr.getResult.mockResolvedValue(result({ relabel_available: true }));
    await renderView();
    vi.useFakeTimers();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Re-label" }));
      await vi.advanceTimersByTimeAsync(0);
    });
    asr.getJob.mockResolvedValue(job({ diarization_status: "complete" }));
    asr.getResult.mockResolvedValue(result());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(announced()).toBe("Re-labelling finished");
  });
});

describe("the move menu without a pointer", () => {
  it("opens on the keyboard with the first choice focused, arrows through, and picks with Enter", async () => {
    asr.getResult.mockResolvedValue(result());
    asr.reassignTurns.mockResolvedValue({
      job_id: "job-1",
      edit_id: "e3",
      speakers: ["SPEAKER_1", "SPEAKER_2"],
      speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Speaker 2" },
      speaker_stats: [],
      created_label: null,
    });
    const user = userEvent.setup();
    await renderView();
    const trigger = within(turnOf("Hello all.")).getByRole("button", { name: /move this turn/ });
    trigger.focus();
    await user.keyboard("{Enter}");
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Speaker 2" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "New speaker" })).toHaveFocus();
    await user.keyboard("{ArrowUp}{Enter}");
    await waitFor(() =>
      expect(asr.reassignTurns).toHaveBeenCalledWith("job-1", { resultRev: 3, segmentIndices: [40, 41], to: "SPEAKER_2" }),
    );
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes on Escape and gives focus back to its button", async () => {
    asr.getResult.mockResolvedValue(result());
    const user = userEvent.setup();
    await renderView();
    const trigger = within(turnOf("Hello all.")).getByRole("button", { name: /move this turn/ });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });
});
