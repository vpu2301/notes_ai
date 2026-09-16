import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CodeInput } from "../src/components/CodeInput";

/** A host that owns the value, the way the login page does. */
function Host({ onComplete }: { onComplete: (v: string) => void }) {
  const [value, setValue] = useState("");
  return <CodeInput value={value} onChange={setValue} onComplete={onComplete} />;
}

const boxes = () => screen.getAllByRole("textbox") as HTMLInputElement[];
const typed = () => boxes().map((b) => b.value).join("");

describe("CodeInput", () => {
  it("advances box by box and submits on the sixth digit", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Host onComplete={onComplete} />);

    await user.keyboard("482913");
    expect(typed()).toBe("482913");
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith("482913");
  });

  it("distributes a pasted code across the boxes", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Host onComplete={onComplete} />);

    boxes()[0]!.focus();
    await user.paste("482913");

    expect(typed()).toBe("482913");
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith("482913");
  });

  it("accepts the grouped form the email shows", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Host onComplete={onComplete} />);

    boxes()[0]!.focus();
    await user.paste("482 913");

    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith("482913");
  });

  it("ignores non-digits", async () => {
    const user = userEvent.setup();
    render(<Host onComplete={vi.fn()} />);

    await user.keyboard("4a8b2c");
    expect(typed()).toBe("482");
  });

  it("does not fire twice when the sixth digit re-renders", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Host onComplete={onComplete} />);

    await user.keyboard("482913");
    // A stray extra keystroke after the code is full must not re-submit.
    await user.keyboard("7");
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("backspaces back through the boxes", async () => {
    const user = userEvent.setup();
    render(<Host onComplete={vi.fn()} />);

    await user.keyboard("4829");
    await user.keyboard("{Backspace}{Backspace}");
    expect(typed()).toBe("48");
  });

  it("names every box for a screen reader and groups them", () => {
    render(<Host onComplete={vi.fn()} />);
    expect(screen.getByRole("group", { name: "Verification code" })).toBeInTheDocument();
    expect(screen.getByLabelText("Digit 1 of 6")).toBeInTheDocument();
    expect(screen.getByLabelText("Digit 6 of 6")).toBeInTheDocument();
  });

  it("claims the one-time-code autofill on the first box only", () => {
    // Naming it on all six makes Safari offer the same code six times.
    render(<Host onComplete={vi.fn()} />);
    const hints = boxes().map((b) => b.getAttribute("autocomplete"));
    expect(hints).toEqual(["one-time-code", "off", "off", "off", "off", "off"]);
  });
});
