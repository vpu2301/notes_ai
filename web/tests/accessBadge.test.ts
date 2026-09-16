import { describe, expect, it } from "vitest";
import type { SearchHit } from "../src/api/types";
import { accessLabel, noteAccess } from "../src/components/AccessBadge";

function hit(extra: Partial<SearchHit>): SearchHit {
  return {
    note_id: "n1",
    code: "NOTE-2026-00001",
    title: "Weekly sync",
    status: "draft",
    template_id: "t1",
    primary_author_id: "u1",
    co_author_ids: [],
    snippet: "",
    updated_at: "2026-09-16T10:00:00Z",
    ...extra,
  };
}

describe("noteAccess", () => {
  it("shows nothing when the server sends no sharing state", () => {
    expect(noteAccess(hit({}))).toBeNull();
  });

  it("calls an unshared private note private", () => {
    expect(accessLabel(noteAccess(hit({ visibility: "private", shared_with_count: 0 }))!)).toBe("Private");
  });

  it("counts the people a private note was shared with", () => {
    expect(accessLabel(noteAccess(hit({ visibility: "private", shared_with_count: 2 }))!)).toBe("Shared with 2");
  });

  it("names workspace visibility", () => {
    expect(accessLabel(noteAccess(hit({ visibility: "workspace", shared_with_count: 3 }))!)).toBe("Workspace");
  });

  it("lets a live public link win over everything else", () => {
    const access = noteAccess(hit({ visibility: "private", shared_with_count: 1, has_public_link: true }));
    expect(access).toEqual({ kind: "public" });
    expect(accessLabel(access!)).toBe("Public");
  });
});
