import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SecretOnce } from "../src/components/SecretOnce";

/**
 * §F/§H: "No secret (recovery codes, TOTP key, device secret) is
 * retrievable after its screen is closed."
 *
 * The component cannot prove the whole property on its own, but it can
 * prove the half that is its job: it writes to no store, and unmounting
 * takes the value with it.
 */
describe("SecretOnce", () => {
  const CODES = ["aaaa-bbbb-cccc", "dddd-eeee-ffff"];

  it("shows every value", () => {
    render(<SecretOnce title="Recovery codes" values={CODES} />);
    for (const code of CODES) expect(screen.getByText(code)).toBeInTheDocument();
  });

  it("writes nothing to browser storage", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<SecretOnce title="Recovery codes" values={CODES} filename="codes.txt" />);
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("leaves nothing in the document once unmounted", () => {
    const { unmount } = render(<SecretOnce title="Recovery codes" values={CODES} />);
    unmount();
    expect(document.body.textContent).not.toContain(CODES[0]!);
  });

  it("copies the values as plain lines", async () => {
    const writeText = vi.fn(async () => undefined);
    // Order matters: `userEvent.setup()` installs its own clipboard stub,
    // so ours has to go on afterwards. (`navigator.clipboard` is
    // getter-only in jsdom, hence defineProperty rather than assignment.)
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<SecretOnce title="Recovery codes" values={CODES} />);
    await user.click(screen.getByRole("button", { name: /copy/i }));

    expect(writeText).toHaveBeenCalledWith(CODES.join("\n"));
  });

  it("survives a clipboard the browser refuses", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async () => {
          throw new Error("denied");
        },
      },
      configurable: true,
    });

    render(<SecretOnce title="Recovery codes" values={CODES} />);
    await user.click(screen.getByRole("button", { name: /copy/i }));

    // The codes are still on screen to be written down — that is the point.
    expect(screen.getByText(CODES[0]!)).toBeInTheDocument();
  });

  it("builds the download in the page and revokes the object URL", async () => {
    const createObjectURL = vi.fn((_blob: Blob) => "blob:x");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const user = userEvent.setup();

    render(<SecretOnce title="Recovery codes" values={CODES} filename="codes.txt" />);
    await user.click(screen.getByRole("button", { name: /download/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    // Nothing is uploaded to make the file — it is a Blob built here.
    expect(createObjectURL.mock.calls[0]![0]).toBeInstanceOf(Blob);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:x");
    vi.unstubAllGlobals();
  });

  it("offers no download when no filename is given", () => {
    render(<SecretOnce title="TOTP key" values={["JBSW Y3DP"]} />);
    expect(screen.queryByRole("button", { name: /download/i })).toBeNull();
  });
});
