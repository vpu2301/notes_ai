import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { AiSettings, ModelParams } from "../src/api/types";
import { ModelBehaviourCard, WritingStyleCard } from "../src/components/ModelBehaviourCard";

const DEFAULTS: ModelParams = {
  temperature: 0,
  context_window_tokens: null,
  max_output_tokens: null,
  max_concurrency: 4,
  facts_per_window: 24,
  retries: "standard",
  ask_temperature: 0.2,
  ask_max_tokens: 700,
};

function settings(over: Partial<AiSettings> = {}): AiSettings {
  return {
    provider: "platform",
    tier: "standard",
    generation_enabled: true,
    effective_provider: "platform",
    effective_tier: "standard",
    processors: [],
    needs_acknowledgement: [],
    month_to_date_cents: 0,
    budget_cents: 2000,
    may_choose_premium: true,
    can_edit: true,
    writing_style: "business",
    model_params: DEFAULTS,
    model_params_effective: DEFAULTS,
    model_params_version: 0,
    model_params_valid: true,
    model_params_limits: {
      temperature: { min: 0, max: 0.7, step: 0.1, default: 0 },
      context_window_tokens: {
        min: 8192,
        max: 262144,
        default: 32768,
        cap: 32768,
        cap_source: "backend",
      },
      max_output_tokens: { min: 512, max: 4096, default: null },
      max_concurrency: { min: 1, max: 8, default: 4, cap: 2, cap_source: "backend" },
      facts_per_window: { min: 8, max: 24, default: 24 },
      retries: { options: ["off", "standard", "thorough"], default: "standard" },
      ask_temperature: { min: 0, max: 1, step: 0.1, default: 0.2 },
      ask_max_tokens: { min: 200, max: 2000, default: 700 },
    },
    model_params_measured: { temperature: { "0.2": null, "0.4": null, "0.7": null } },
    ...over,
  };
}

function card(
  s: AiSettings,
  onSave = vi.fn().mockResolvedValue(undefined),
  url = "/settings/data?view=writing&advanced=1",
  overriddenBy: string | null = null,
) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <WritingStyleCard settings={s} busy={false} onSave={onSave} overriddenBy={overriddenBy} />
      <ModelBehaviourCard settings={s} busy={false} onSave={onSave} />
    </MemoryRouter>,
  );
  return onSave;
}

describe("model behaviour", () => {
  it("shows a member the values and no inputs", () => {
    card(settings({ can_edit: false }));
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByRole("button", { name: "Academic" })).toBeDisabled();
    expect(screen.getByText("Only a workspace admin can change this.")).toBeInTheDocument();
  });

  it("saves the whole parameter set", () => {
    const onSave = card(settings());
    fireEvent.change(screen.getByRole("spinbutton", { name: "Temperature" }), {
      target: { value: "0.4" },
    });
    expect(screen.getByText("Not yet measured on the gold set.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save model settings" }));
    expect(onSave).toHaveBeenCalledWith(
      { model_params: { ...DEFAULTS, temperature: 0.4 } },
      expect.any(Function),
    );
    const toast = onSave.mock.calls[0]![1] as (s: AiSettings) => string;
    expect(toast(settings({ model_params_version: 2 }))).toBe("Model settings saved (v2).");
  });

  it("names the model's cap on a value it limited", () => {
    const capped = { ...DEFAULTS, context_window_tokens: 32768 };
    card(
      settings({ model_params: capped, model_params_effective: capped, model_params_version: 2 }),
    );
    expect(screen.getByText(/capped at 32,768 by the model/)).toBeInTheDocument();
  });

  it("resets only after a confirmation", () => {
    const onSave = card(settings());
    fireEvent.click(screen.getByRole("button", { name: "Reset to recommended" }));
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onSave).toHaveBeenCalledWith({ reset_model_params: true }, expect.any(String));
  });

  it("saves a style on click", () => {
    const onSave = card(settings());
    fireEvent.click(screen.getByRole("button", { name: "Academic" }));
    expect(onSave).toHaveBeenCalledWith(
      { writing_style: "academic" },
      "Notes will be written in the academic style.",
    );
  });

  it("says the style is overridden by the instructions and stays usable", () => {
    const onSave = card(settings(), undefined, undefined, "academic");
    expect(screen.getByText(/Overridden by your instructions/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Formal" }));
    expect(onSave).toHaveBeenCalledWith({ writing_style: "formal" }, expect.any(String));
  });

  it("says when the saved values need a reset", () => {
    card(settings({ model_params_valid: false }));
    expect(screen.getByText(/Reset needed/)).toBeInTheDocument();
  });
});

describe("generation status with model settings", () => {
  it("names the settings version a note was written with", async () => {
    const { setAccessToken, setSessionListener } = await import("../src/api/http");
    const { GenerationStatus } = await import("../src/components/GenerationStatus");
    const { ToasterProvider } = await import("../src/components/Toaster");
    setSessionListener({});
    setAccessToken("x");
    const view = {
      id: "g1",
      status: "complete",
      step: null,
      windows_total: 2,
      windows_done: 2,
      windows_failed: 0,
      failed_ranges: [],
      prompt_version: "2026-10-19.1",
      model_id: "m",
      error_kind: null,
      created_at: "2026-10-19T10:00:00Z",
      finished_at: "2026-10-19T10:01:00Z",
      suggested_sections: [],
      sections_written: 3,
      model_settings_version: 2,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(view), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    render(
      <MemoryRouter>
        <ToasterProvider>
          <GenerationStatus noteId="n1" />
        </ToasterProvider>
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(document.querySelector(".gen-instructions")?.textContent).toBe(
        "Written with model settings v2",
      ),
    );
    vi.unstubAllGlobals();
  });
});
