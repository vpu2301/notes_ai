// Shared by the AI notes settings panels: labels, a configuration diff, draft storage.
import type {
  ExperimentSummary,
  ProfileConfig,
  ProfileStage,
  PromptProfile,
  PromptProfilesView,
} from "../../../api/types";

export const STAGES: ProfileStage[] = ["extraction", "composition", "verification"];

export const STAGE_LABELS: Record<ProfileStage, string> = {
  extraction: "Extract facts",
  composition: "Write notes",
  verification: "Verify meaning",
};

export const STAGE_HELP: Record<ProfileStage, string> = {
  extraction: "Reads the transcript in parts and lists what was said, each point with its quote.",
  composition:
    "Writes the summary, the topic bullets and their headings from the verified points. Keep its named sections (GENERAL, SUMMARY SUBTASK, TOPIC/BULLET SUBTASK, HEADING SUBTASK, CHRONOLOGY): each call gets GENERAL plus its own.",
  verification:
    "Checks that each restated point, and every written line before the note is saved, means what was said.",
};

/** What a call of the run is, in words. */
export const CALL_LABELS: Record<string, string> = {
  extraction: "Extract facts",
  context: "Understand the conversation",
  "composition.topic": "Write topic bullets and heading",
  "composition.bullets": "Write topic bullets (small model)",
  "composition.heading": "Write a topic heading (small model)",
  "composition.summary": "Write the summary",
  "verification.meaning": "Verify a point's meaning",
  "verification.final": "Final check of every written line",
  deduplication: "Merge repeated points",
  participants: "Check who takes part",
};

export const SOURCE_LABELS: Record<string, string> = {
  profile: "this version's text",
  bundled: "bundled text",
  not_applied: "edited, but not sent here",
  code: "code-owned, read-only",
};

export const LANGUAGES = [
  { value: "auto", label: "Auto" },
  { value: "en", label: "English" },
  { value: "de", label: "German" },
  { value: "uk", label: "Ukrainian" },
] as const;

export const LENGTHS = [
  { value: "short", label: "Short" },
  { value: "standard", label: "Standard" },
  { value: "detailed", label: "Detailed" },
] as const;

export const EMPTY_CONFIG: ProfileConfig = {
  stages: {},
  models: {},
  params: {},
  output_language: "auto",
  length: "standard",
};

export function normalise(config: Partial<ProfileConfig> | null | undefined): ProfileConfig {
  return {
    stages: { ...(config?.stages ?? {}) },
    models: { ...(config?.models ?? {}) },
    params: { ...(config?.params ?? {}) },
    output_language: config?.output_language ?? "auto",
    length: config?.length ?? "standard",
  };
}

/** "Broadcasts · v3", or "Bundled profile" for null. */
export function versionLabel(view: PromptProfilesView | null, versionId: string | null): string {
  if (!versionId) return "Bundled profile";
  for (const p of view?.profiles ?? []) {
    const v = p.versions.find((x) => x.id === versionId);
    if (v) return `${p.name} · v${v.version_number}`;
  }
  return "Unknown version";
}

export function profileOf(view: PromptProfilesView | null, versionId: string | null): PromptProfile | null {
  return view?.profiles.find((p) => p.versions.some((v) => v.id === versionId)) ?? null;
}

export function moneyOrUnknown(cents: number | null | undefined): string {
  return cents === null || cents === undefined ? "unknown" : `$${(cents / 100).toFixed(2)}`;
}

export interface ConfigDiff {
  prompts: ProfileStage[];
  models: ProfileStage[];
  params: ProfileStage[];
  language: boolean;
  length: boolean;
  /** Prompts AND models changed: a difference cannot be attributed to one of them. */
  multiple: boolean;
  empty: boolean;
}

export function diffConfigs(a: ProfileConfig, b: ProfileConfig): ConfigDiff {
  const prompts = STAGES.filter((s) => (a.stages[s] ?? null) !== (b.stages[s] ?? null));
  const models = STAGES.filter((s) => (a.models[s] ?? null) !== (b.models[s] ?? null));
  const params = STAGES.filter(
    (s) => JSON.stringify(a.params[s] ?? {}) !== JSON.stringify(b.params[s] ?? {}),
  );
  const language = a.output_language !== b.output_language;
  const length = a.length !== b.length;
  const kinds = [prompts.length > 0, models.length > 0 || params.length > 0, language || length].filter(Boolean);
  return {
    prompts,
    models,
    params,
    language,
    length,
    multiple: kinds.length > 1,
    empty: kinds.length === 0,
  };
}

export function describeDiff(d: ConfigDiff): string[] {
  const out: string[] = [];
  if (d.prompts.length) out.push(`Instructions: ${d.prompts.map((s) => STAGE_LABELS[s]).join(", ")}`);
  if (d.models.length) out.push(`Model: ${d.models.map((s) => STAGE_LABELS[s]).join(", ")}`);
  if (d.params.length) out.push(`Model settings: ${d.params.map((s) => STAGE_LABELS[s]).join(", ")}`);
  if (d.language) out.push("Output language");
  if (d.length) out.push("Length");
  return out;
}

/** Lines removed and added between two texts — enough to review an edit, not a full diff tool. */
export function lineDiff(before: string, after: string): { removed: string[]; added: string[] } {
  const a = before.split("\n");
  const b = after.split("\n");
  const inA = new Set(a);
  const inB = new Set(b);
  return {
    removed: a.filter((l) => l.trim() && !inB.has(l)),
    added: b.filter((l) => l.trim() && !inA.has(l)),
  };
}

export function lastFinished(experiments: ExperimentSummary[]): ExperimentSummary | null {
  return experiments[0] ?? null;
}

// ── Unsaved drafts: the browser keeps them; the server never sees them until Save ──

const DRAFT_PREFIX = "aiNotesDraft:";

export interface StoredDraft {
  profileId: string;
  baseVersionId: string | null;
  config: ProfileConfig;
}

export function loadDraft(profileId: string): StoredDraft | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_PREFIX + profileId);
    return raw ? (JSON.parse(raw) as StoredDraft) : null;
  } catch {
    return null;
  }
}

export function storeDraft(draft: StoredDraft): void {
  try {
    window.localStorage.setItem(DRAFT_PREFIX + draft.profileId, JSON.stringify(draft));
  } catch {
    // Private mode or full storage: the draft lives only in this tab.
  }
}

export function dropDraft(profileId: string): void {
  try {
    window.localStorage.removeItem(DRAFT_PREFIX + profileId);
  } catch {
    // Nothing stored, nothing to drop.
  }
}

export function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function mmss(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
