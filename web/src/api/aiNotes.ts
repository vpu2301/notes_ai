// How notes are written: profiles (immutable versions, one active) and A/B experiments.
// Every call is re-checked server-side; nothing here is a permission boundary.
import { api } from "./http";
import type {
  ActivationRecord,
  ActiveProfile,
  ExperimentEstimate,
  ExperimentRequest,
  ExperimentSummary,
  ExperimentView,
  ModelCapabilities,
  ProfileConfig,
  ProfilePreview,
  ProfileVersionSummary,
  ProfileVersionView,
  PromptProfile,
  PromptProfilesView,
  ReviewRequest,
  RunArtifact,
} from "./types";

export function listProfiles(): Promise<PromptProfilesView> {
  return api<PromptProfilesView>("note", "/v1/ai/prompt-profiles");
}

export function createProfile(body: {
  name: string;
  description?: string;
  copy_of_version_id?: string | null;
}): Promise<PromptProfile> {
  return api<PromptProfile>("note", "/v1/ai/prompt-profiles", { method: "POST", json: body });
}

/** Saves an immutable version. It never activates anything. */
export function saveVersion(profileId: string, config: ProfileConfig): Promise<ProfileVersionSummary> {
  return api<ProfileVersionSummary>("note", `/v1/ai/prompt-profiles/${profileId}/versions`, {
    method: "POST",
    json: { config },
  });
}

export function getVersion(profileId: string, versionId: string, language: string): Promise<ProfileVersionView> {
  return api<ProfileVersionView>("note", `/v1/ai/prompt-profiles/${profileId}/versions/${versionId}`, {
    query: { language },
  });
}

/** Validates and resolves an unsaved draft; saves nothing. */
export function previewDraft(config: ProfileConfig, language: string): Promise<ProfilePreview> {
  return api<ProfilePreview>("note", "/v1/ai/prompt-profiles/preview", {
    method: "POST",
    json: { config, language },
  });
}

/** Moves the active pointer from the revision this page saw (activation and rollback). */
export function activateVersion(
  profileId: string,
  body: { version_id: string | null; expected_active_revision: number; evaluation_ref?: string | null },
): Promise<ActiveProfile> {
  return api<ActiveProfile>("note", `/v1/ai/prompt-profiles/${profileId}/activate`, {
    method: "POST",
    json: body,
  });
}

export function activationHistory(): Promise<ActivationRecord[]> {
  return api<ActivationRecord[]>("note", "/v1/ai/prompt-profiles/history");
}

export function modelCapabilities(): Promise<ModelCapabilities> {
  return api<ModelCapabilities>("note", "/v1/ai/model-capabilities");
}

export function estimateExperiment(body: ExperimentRequest): Promise<ExperimentEstimate> {
  return api<ExperimentEstimate>("note", "/v1/ai/experiments/estimate", { method: "POST", json: body });
}

export function startExperiment(body: ExperimentRequest): Promise<ExperimentView> {
  return api<ExperimentView>("note", "/v1/ai/experiments", { method: "POST", json: body });
}

export function listExperiments(): Promise<ExperimentSummary[]> {
  return api<ExperimentSummary[]>("note", "/v1/ai/experiments");
}

export function getExperiment(id: string): Promise<ExperimentView> {
  return api<ExperimentView>("note", `/v1/ai/experiments/${id}`);
}

export function cancelExperiment(id: string): Promise<ExperimentView> {
  return api<ExperimentView>("note", `/v1/ai/experiments/${id}/cancel`, { method: "POST" });
}

export function getRunArtifact(experimentId: string, runId: string): Promise<RunArtifact> {
  return api<RunArtifact>("note", `/v1/ai/experiments/${experimentId}/runs/${runId}/artifact`);
}

export function submitReview(experimentId: string, body: ReviewRequest): Promise<{ id: string }> {
  return api<{ id: string }>("note", `/v1/ai/experiments/${experimentId}/reviews`, {
    method: "POST",
    json: body,
  });
}
