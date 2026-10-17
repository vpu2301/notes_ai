import { beforeEach, describe, expect, it, vi } from "vitest";
import { isMine, loadTitles, markMine, rememberTitle, scopeCaptures } from "../src/lib/captures";
import { roleLabel, workspaceLabel } from "../src/api/types";

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

/** Node 25's own (file-less) `localStorage` shadows jsdom's here; give the module a working one. */
function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  };
}

describe("capture bookkeeping is per workspace", () => {
  // The active workspace is module state: each test starts from a workspace the previous one did not end in.
  beforeEach(() => vi.stubGlobal("localStorage", memoryStorage()));

  it("moves pre-workspace keys into the active workspace once", () => {
    localStorage.setItem("notesai.capture.titles", JSON.stringify({ "job-1": "Kickoff" }));
    localStorage.setItem("notesai.capture.mine", JSON.stringify(["job-1"]));

    scopeCaptures(A);

    expect(localStorage.getItem("notesai.capture.titles")).toBeNull();
    expect(localStorage.getItem("notesai.capture.mine")).toBeNull();
    expect(JSON.parse(localStorage.getItem(`notesai.${A}.capture.titles`)!)).toEqual({ "job-1": "Kickoff" });
    expect(loadTitles()).toEqual({ "job-1": "Kickoff" });
    expect(isMine("job-1")).toBe(true);

    // The other workspace starts empty; nothing is moved twice.
    scopeCaptures(B);
    expect(loadTitles()).toEqual({});
    expect(isMine("job-1")).toBe(false);
  });

  it("keeps writes in the workspace they were made in", () => {
    scopeCaptures(A);
    rememberTitle("job-a", "In A");
    markMine("job-a");
    scopeCaptures(B);
    rememberTitle("job-b", "In B");

    expect(loadTitles()).toEqual({ "job-b": "In B" });
    scopeCaptures(A);
    expect(loadTitles()).toEqual({ "job-a": "In A" });
    expect(isMine("job-a")).toBe(true);
  });

  it("does not overwrite a workspace's own value with a stale unscoped one", () => {
    localStorage.setItem(`notesai.${C}.capture.titles`, JSON.stringify({ kept: "yes" }));
    localStorage.setItem("notesai.capture.titles", JSON.stringify({ stale: "no" }));
    scopeCaptures(C);
    expect(loadTitles()).toEqual({ kept: "yes" });
    expect(localStorage.getItem("notesai.capture.titles")).toBeNull();
  });
});

describe("workspace roles", () => {
  it("decodes guest and the legacy assistant, and passes an unknown role through", () => {
    expect(roleLabel("guest")).toBe("Guest");
    expect(roleLabel("viewer")).toBe("Viewer");
    expect(roleLabel("assistant")).toBe("Assistant");
    expect(roleLabel("auditor")).toBe("auditor");
  });

  it("names a personal workspace Personal whatever its display name", () => {
    expect(workspaceLabel({ kind: "personal", name: "Sam's workspace" })).toBe("Personal");
    expect(workspaceLabel({ kind: "team", name: "Acme Inc" })).toBe("Acme Inc");
    expect(workspaceLabel({ name: "Acme Inc" })).toBe("Acme Inc");
  });
});
