import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Segmented } from "../src/components/Segmented";

const OPTIONS = [
  { value: "overview", label: "Overview" },
  { value: "plans", label: "Plans" },
] as const;

function Harness() {
  const [value, setValue] = useState<"overview" | "plans">("overview");
  return <Segmented label="Billing" options={OPTIONS} value={value} onChange={setValue} />;
}

describe("Segmented", () => {
  it("is a radio group that follows clicks and arrow keys", () => {
    render(<Harness />);
    const overview = screen.getByRole("radio", { name: "Overview" });
    const plans = screen.getByRole("radio", { name: "Plans" });
    expect(overview).toHaveAttribute("aria-checked", "true");

    fireEvent.click(plans);
    expect(plans).toHaveAttribute("aria-checked", "true");
    expect(overview).toHaveAttribute("tabindex", "-1");

    fireEvent.keyDown(screen.getByRole("radiogroup", { name: "Billing" }), { key: "ArrowRight" });
    expect(overview).toHaveAttribute("aria-checked", "true");
  });
});
