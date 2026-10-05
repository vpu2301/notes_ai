import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSessionListener } from "../src/api/http";
import { SharingStatsPage } from "../src/pages/SharingStatsPage";

const STATS = {
  days: 30,
  links_created: 10,
  links_sent: 8,
  links_opened: 6,
  links_responded: 3,
  cta_clicks: 2,
  item_responses: 5,
  disputes: 1,
  opted_out: 1,
  dispute_rate: 0.2,
  top_senders: [{ display_name: "Anna Koval", links: 7 }],
};

beforeEach(() => {
  setSessionListener({});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(STATS), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("/admin/sharing", () => {
  it("renders the four tiles from the counts", async () => {
    render(<SharingStatsPage />);
    expect(await screen.findByText("Links sent")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument(); // 6 of 8 opened
    expect(screen.getByText("50%")).toBeInTheDocument(); // 3 of 6 responded
    expect(screen.getByText(/20% disputed/)).toBeInTheDocument();
    expect(screen.getByText("Anna Koval")).toBeInTheDocument();
  });
});
