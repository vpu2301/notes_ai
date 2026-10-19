import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SectionNav } from "../src/components/SectionNav";

const ITEMS = [
  { id: "sec-summary", title: "Summary" },
  { id: "sec-scope", title: "Scope" },
  { id: "sec-review", title: "Review and acceptance" },
];

function page() {
  return render(
    <>
      {ITEMS.map((i) => (
        <section key={i.id} id={i.id} className="doc-section">
          {i.title}
        </section>
      ))}
      <SectionNav items={ITEMS} />
    </>,
  );
}

describe("section navigator", () => {
  it("shows one mark per headed section and opens the list on hover", () => {
    const { container } = page();
    expect(container.querySelectorAll(".section-nav-mark")).toHaveLength(3);
    const nav = screen.getByRole("navigation", { name: "Sections of this note" });
    expect(nav).not.toHaveClass("open");
    fireEvent.mouseEnter(nav);
    expect(nav).toHaveClass("open");
    fireEvent.mouseLeave(nav);
    expect(nav).not.toHaveClass("open");
  });

  it("tints a section while its heading is hovered and scrolls to it on click", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    page();
    const target = document.getElementById("sec-review")!;
    const item = screen.getByRole("button", { name: "Review and acceptance" });
    fireEvent.mouseEnter(item);
    expect(target).toHaveClass("nav-target");
    fireEvent.click(item);
    expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(target).not.toHaveClass("nav-target");
    expect(item).toHaveAttribute("aria-current", "location");
  });

  it("is absent for a note with fewer than two headed sections", () => {
    render(<SectionNav items={[ITEMS[0]!]} />);
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
