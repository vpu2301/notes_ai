import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResponsesPanel } from "../src/components/ResponsesPanel";
import { ToasterProvider } from "../src/components/Toaster";
import type { ItemView } from "../src/api/types";

const ITEM: ItemView = {
  id: "i1",
  item_key: "k1",
  position: 0,
  text: "send the pricing proposal",
  owner_label: "Anna",
  owner_confidence: 0.5,
  due_date: "2026-09-18",
  due_text: "18 Sep",
  due_confidence: 1,
  status: "open",
  counts: { confirms: 2, dones: 0, disputes: 1 },
  responses: [
    {
      id: "r1",
      link_id: "l1",
      link_label: "Tom @ Client",
      kind: "dispute",
      item_key: "k1",
      section_key: null,
      comment: "<img src=x onerror=alert(1)> It was Friday",
      created_at: "2026-09-16T12:00:00Z",
      cleared_at: null,
    },
  ],
};

describe("responses tab", () => {
  it("renders counts, the sender-labelled dispute, and the comment as text", () => {
    render(
      <ToasterProvider>
        <ResponsesPanel noteId="n1" items={[ITEM]} responses={ITEM.responses} sections={[]} onItems={() => {}} onResponses={() => {}} />
      </ToasterProvider>,
    );
    expect(screen.getByText("2 confirmed · 1 disputed")).toBeInTheDocument();
    expect(screen.getByText("Tom @ Client")).toBeInTheDocument();
    expect(screen.getByText(/check owner/)).toBeInTheDocument();
    const comment = screen.getByText(/It was Friday/);
    // The markup arrived as text and stays text: no element was created from it.
    expect(comment.textContent).toBe("<img src=x onerror=alert(1)> It was Friday");
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByRole("button", { name: /mark done/i })).toBeInTheDocument();
  });
});
